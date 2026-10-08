//
//  MemoryStore.swift
//  记忆存储抽象 + 两套实现。
//
//  背景：client.py 依赖 `from memory.store import all_memories, remember`，
//  但当前工程里**没有** memory/store.py（/Users/zhongyuanliu/deepseek 下无 memory/ 目录），
//  所以 Python 版本连 import 都过不去。移植时把这个依赖显式化成协议：
//      all_memories(agent_id) -> dict      =>  allMemories(agentID:)
//      remember(agent_id, k, v)            =>  remember(agentID:key:value:)
//  这样既可以对接你真实的 memory 模块，也能用这里的 JSON 文件实现直接跑起来。
//
//  两个实现：
//    * JSONFileMemoryStore(directory:)        —— 普通目录，macOS 测试 / 非沙箱宿主
//    * JSONFileMemoryStore(sandbox:)          —— iOS 沙箱内的推荐位置，
//                                                写入走 AppSandbox（原子写 + 文件保护 + 备份策略）
//

import AppSandboxKit
import Foundation

// MARK: - 错误

public enum MemoryStoreError: Error, CustomStringConvertible, Equatable {
    case invalidAgentID(String)
    case unreadable(URL, String)
    case malformedStore(URL, String)
    case writeFailed(URL, String)
    case directoryUnavailable(URL, String)

    public var description: String {
        switch self {
        case .invalidAgentID(let agentID):
            return "非法的 agent id: \"\(agentID)\"。agent id 会被用作文件名，"
                 + "因此不允许为空、不允许是 . 或 ..，也不允许包含 / \\ : 或 NUL。"
        case .unreadable(let url, let detail):
            return "读取记忆文件失败: \(url.path) (\(detail))"
        case .malformedStore(let url, let detail):
            return "记忆文件不是合法的 JSON 对象: \(url.path) (\(detail))"
        case .writeFailed(let url, let detail):
            return "写入记忆文件失败: \(url.path) (\(detail))"
        case .directoryUnavailable(let url, let detail):
            return "记忆目录不可用: \(url.path) (\(detail))"
        }
    }
}

// MARK: - 协议

/// 记忆存储。对应 client.py 里用到的 `memory.store` 两个函数。
public protocol MemoryStore {
    /// 对应 `all_memories(agent_id) -> dict`。
    func allMemories(agentID: String) throws -> [String: JSONValue]

    /// 对应 `remember(agent_id, k, v)`：只在存储里增改这一个 key，不动其它 key。
    func remember(agentID: String, key: String, value: JSONValue) throws

    /// 批量增改。默认实现逐条调用 `remember`，与 client.py 的循环语义完全一致；
    /// 文件实现会重写这一方法，把 N 次写盘合并成 1 次。
    func rememberAll(agentID: String, values: [String: JSONValue]) throws
}

public extension MemoryStore {
    func rememberAll(agentID: String, values: [String: JSONValue]) throws {
        for (key, value) in values {
            try remember(agentID: agentID, key: key, value: value)
        }
    }
}

// MARK: - JSON 文件实现

/// 每个 agent 一个 JSON 文件：`<directory>/<agentID>.json`，内容 `{"key": <任意 JSON>}`。
///
/// - 传入 `sandbox` 时，写入会走 `AppSandbox.write`，从而获得：
///   原子写（先写临时文件再 rename）、iOS 文件保护等级，以及「明确不排除 iCloud 备份」
///   —— 记忆是用户数据，被排除出备份就是丢数据，所以这里传 `excludeFromBackup: false`。
public struct JSONFileMemoryStore: MemoryStore {

    /// 记忆文件所在目录。
    public let directory: URL

    /// 非 nil 时写入走 AppSandbox。
    private let sandbox: AppSandbox?

    // MARK: 初始化

    /// 普通目录。目录不存在会自动创建。
    public init(directory: URL) throws {
        let standardized = directory.standardizedFileURL
        self.directory = standardized
        self.sandbox = nil
        try JSONFileMemoryStore.ensureDirectory(standardized)
    }

    /// iOS 沙箱内的推荐位置：`Library/Application Support/<subdirectory>`。
    ///
    /// 选 Application Support 而不是 Documents：记忆是应用自身数据，用户不该在
    /// 「文件」App 里翻到并误删；也不选 Caches，因为 Caches 会被系统清理。
    public init(sandbox: AppSandbox, subdirectory: String = "Memory") throws {
        let base = try sandbox.url(for: .applicationSupport) // 默认 createIfNeeded = true
        let directory = base.appendingPathComponent(subdirectory, isDirectory: true)
        self.directory = directory
        self.sandbox = sandbox
        try sandbox.ensureDirectory(directory)
    }

    // MARK: MemoryStore

    public func allMemories(agentID: String) throws -> [String: JSONValue] {
        let url = try fileURL(agentID: agentID)
        guard FileManager.default.fileExists(atPath: url.path) else { return [:] }
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            throw MemoryStoreError.unreadable(url, "\(error)")
        }
        if data.isEmpty { return [:] }
        do {
            let decoded = try JSONDecoder().decode(JSONValue.self, from: data)
            guard let object = decoded.objectValue else {
                throw MemoryStoreError.malformedStore(url, "顶层不是 JSON 对象")
            }
            return object
        } catch let error as MemoryStoreError {
            throw error
        } catch {
            throw MemoryStoreError.malformedStore(url, "\(error)")
        }
    }

    public func remember(agentID: String, key: String, value: JSONValue) throws {
        var memories = try allMemories(agentID: agentID)
        memories[key] = value
        try write(memories, agentID: agentID)
    }

    /// 覆盖默认实现：合并后只写一次盘。
    public func rememberAll(agentID: String, values: [String: JSONValue]) throws {
        guard !values.isEmpty else { return }
        var memories = try allMemories(agentID: agentID)
        for (key, value) in values {
            memories[key] = value
        }
        try write(memories, agentID: agentID)
    }

    // MARK: 内部

    private func write(_ memories: [String: JSONValue], agentID: String) throws {
        let url = try fileURL(agentID: agentID)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let data: Data
        do {
            data = try encoder.encode(JSONValue.object(memories))
        } catch {
            throw MemoryStoreError.writeFailed(url, "\(error)")
        }

        do {
            if let sandbox {
                try sandbox.write(
                    data,
                    to: url,
                    excludeFromBackup: false, // 记忆必须进备份：排除掉就等于丢数据
                    protection: .completeUntilFirstUserAuthentication
                )
            } else {
                try data.write(to: url, options: [.atomic])
            }
        } catch {
            throw MemoryStoreError.writeFailed(url, "\(error)")
        }
    }

    private func fileURL(agentID: String) throws -> URL {
        let name = try JSONFileMemoryStore.safeFileName(agentID)
        return directory.appendingPathComponent(name + ".json", isDirectory: false)
    }

    /// agent id 直接来自命令行 / 远端，会被拼进文件路径 —— 必须挡住路径穿越。
    static func safeFileName(_ agentID: String) throws -> String {
        let forbidden = CharacterSet(charactersIn: "/\\:")
        let trimmed = agentID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              trimmed != ".",
              trimmed != "..",
              !trimmed.contains("\u{0}"),
              trimmed.rangeOfCharacter(from: forbidden) == nil,
              // Windows 上还有一堆保留字，这里只挡最容易出事的相对路径与分隔符
              !trimmed.hasPrefix("~")
        else {
            throw MemoryStoreError.invalidAgentID(agentID)
        }
        return trimmed
    }

    private static func ensureDirectory(_ url: URL) throws {
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory) {
            guard isDirectory.boolValue else {
                throw MemoryStoreError.directoryUnavailable(url, "同名文件已存在且不是目录")
            }
            return
        }
        do {
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        } catch {
            throw MemoryStoreError.directoryUnavailable(url, "\(error)")
        }
    }
}
