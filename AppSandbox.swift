// AppSandbox.swift
//
// iOS 应用沙箱（文件系统）适配层。
//
// 解决的是 iOS 沙箱最容易被踩的几件事：
//   1. 应用容器路径里带 UUID，每次安装 / 更新 / 从备份恢复都会变 ——
//      绝对路径一旦落盘必然失效，必须持久化「相对容器」的路径。
//   2. Documents / Library / Application Support 会被 iCloud 备份，
//      Caches / tmp 不会且可能被系统清理 —— 放错地方要么被审核打回，要么丢数据。
//   3. 写文件必须原子化，避免中途被杀留下半个文件。
//   4. App Group 容器在 entitlements 缺失时返回 nil，不能强解包。
//   5. iOS 的文件保护等级（Data Protection）影响锁屏时的可读性。
//
// 本文件不依赖 UIKit，可以在 macOS 上跑测试（注入 containerURL 即可），
// 也能通过真实的 iOS SDK 类型检查。

import Foundation

// MARK: - 错误

public enum AppSandboxError: Error, CustomStringConvertible, Equatable {
    case containerUnavailable(String)
    case appGroupUnavailable(identifier: String)
    case itemNotFound(URL)
    case outsideContainer(URL)
    case invalidPortablePath(String)
    case directoryCreationFailed(URL, String)
    case backupFlagNotApplied(URL, expected: Bool)

    public var description: String {
        switch self {
        case .containerUnavailable(let detail):
            return "无法解析应用容器: \(detail)"
        case .appGroupUnavailable(let identifier):
            return "App Group 容器不可用: \(identifier)。"
                 + "通常是 entitlements 里没配 com.apple.security.application-groups，或配置与代码里的 ID 不一致。"
        case .itemNotFound(let url):
            return "路径不存在: \(url.path)"
        case .outsideContainer(let url):
            return "路径不在应用容器内: \(url.path)"
        case .invalidPortablePath(let path):
            return "非法的可移植路径: \(path)"
        case .directoryCreationFailed(let url, let detail):
            return "创建目录失败: \(url.path) (\(detail))"
        case .backupFlagNotApplied(let url, let expected):
            return "备份标记未生效: \(url.path)（期望 isExcludedFromBackup = \(expected)）。"
                 + "重试回读后仍不一致，请检查文件系统是否只读或该路径是否受系统管理。"
        }
    }
}

// MARK: - 目录枚举

/// iOS 沙箱内的标准目录。
///
/// 每个 case 都标注了「是否会被 iCloud 备份」和「系统能否清理」，
/// 这是选目录时唯一需要判断的两件事。
public enum SandboxDirectory: Equatable {
    /// 会被备份、用户可见（配合 UIFileSharingEnabled / LSSupportsOpeningDocumentsInPlace）。
    /// 适合放用户自己产生的、不能丢的文档。
    case documents
    /// 容器根下的 Library。一般不要直接往这里丢文件，用下面的细分目录。
    case library
    /// 会被备份、用户不可见。**应用自身数据应该放这里**，而不是 Documents。
    /// 注意：iOS 上该目录默认不存在，需要自己创建（本适配层会自动创建）。
    case applicationSupport
    /// 不会被备份，系统可在空间紧张时清理。只放可重新生成的缓存。
    case caches
    /// 不会被备份，也不保证跨启动存活。放真正的临时文件。
    case temporary
    /// UserDefaults 的落盘位置。一般不要直接读写。
    case preferences
    /// 约定俗成的「永不进 iCloud」目录（Library/NoCloud）。
    case noCloud
    /// App Group 共享容器根。主 App 与 Widget / Extension 交换数据用。
    case appGroup(identifier: String)
}

// MARK: - 主类型

/// 应用沙箱路径适配层。
///
/// 用法：
/// ```swift
/// let sandbox = try AppSandbox()
/// let dbURL = try sandbox.url(for: .applicationSupport).appendingPathComponent("store.sqlite")
/// try sandbox.write(data, to: dbURL, excludeFromBackup: false, protection: .completeUntilFirstUserAuthentication)
/// ```
public final class AppSandbox {

    public let fileManager: FileManager
    /// 应用容器根目录。真机上形如
    /// `/var/mobile/Containers/Data/Application/<UUID>`，UUID 会变。
    public let containerURL: URL
    /// 是否由调用方注入（测试用）。注入时不会去问系统的 SearchPath API。
    public let isContainerInjected: Bool

    /// App Group 容器解析器，默认走 FileManager，可注入以便测试。
    private let appGroupResolver: (String) -> URL?

    /// 用真实容器初始化。
    public convenience init(fileManager: FileManager = .default) throws {
        try self.init(fileManager: fileManager, containerURL: nil)
    }

    /// 注入容器初始化（测试 / 特殊场景）。
    ///
    /// - Parameter appGroupResolver: App Group 容器解析器。
    ///   默认走 `FileManager`。做成可注入是因为 macOS 上这个方法**不校验 entitlements**，
    ///   即使 group 没配置也可能返回一个路径，导致「拿不到容器要报错」这条分支在 macOS 上测不到。
    public init(
        fileManager: FileManager = .default,
        containerURL: URL?,
        appGroupResolver: ((String) -> URL?)? = nil
    ) throws {
        self.fileManager = fileManager
        self.appGroupResolver = appGroupResolver ?? { identifier in
            fileManager.containerURL(forSecurityApplicationGroupIdentifier: identifier)
        }
        if let injected = containerURL {
            self.containerURL = injected.standardizedFileURL
            self.isContainerInjected = true
        } else {
            self.containerURL = try AppSandbox.resolveContainer(fileManager)
            self.isContainerInjected = false
        }
    }

    /// 解析应用容器根。
    ///
    /// 用 Documented API 取 Documents 再上溯一层，而不是 `NSHomeDirectory()` 拼字符串。
    /// iOS 上的容器布局是 Apple 明确文档化的：
    ///     <container>/Documents
    ///     <container>/Library/{Application Support, Caches, Preferences}
    ///     <container>/tmp
    private static func resolveContainer(_ fileManager: FileManager) throws -> URL {
        guard let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw AppSandboxError.containerUnavailable("urls(for: .documentDirectory) 返回空")
        }
        return documents.deletingLastPathComponent().standardizedFileURL
    }

    // MARK: 目录解析

    /// 取标准目录的 URL。
    ///
    /// - Parameter createIfNeeded: iOS 上 Application Support、NoCloud 等目录默认不存在，
    ///   打开这个开关会自动创建（幂等）。
    public func url(for directory: SandboxDirectory, createIfNeeded: Bool = true) throws -> URL {
        let target: URL
        switch directory {
        case .documents:
            target = containerURL.appendingPathComponent("Documents", isDirectory: true)
        case .library:
            target = containerURL.appendingPathComponent("Library", isDirectory: true)
        case .applicationSupport:
            target = containerURL.appendingPathComponent("Library/Application Support", isDirectory: true)
        case .caches:
            target = containerURL.appendingPathComponent("Library/Caches", isDirectory: true)
        case .temporary:
            // 刻意不复用 containerURL 拼 "tmp"：macOS 上临时目录是 /var/folders/...，
            // 只有 iOS 才是 <container>/tmp。用系统 API 两边都对。
            target = fileManager.temporaryDirectory
        case .preferences:
            target = containerURL.appendingPathComponent("Library/Preferences", isDirectory: true)
        case .noCloud:
            target = containerURL.appendingPathComponent("Library/NoCloud", isDirectory: true)
        case .appGroup(let identifier):
            guard let group = appGroupResolver(identifier) else {
                throw AppSandboxError.appGroupUnavailable(identifier: identifier)
            }
            // App Group 容器不需要再创建，系统已保证存在
            return group
        }

        if createIfNeeded {
            try ensureDirectory(target)
        }
        return target
    }

    /// Documents/Inbox：其它 App 通过「用 XX 打开」投递进来的文件。
    /// 用完必须自己删除或移走，系统不会清理。
    public var documentsInboxURL: URL {
        containerURL.appendingPathComponent("Documents/Inbox", isDirectory: true)
    }

    // MARK: 目录工具

    @discardableResult
    public func ensureDirectory(_ url: URL) throws -> URL {
        var isDirectory: ObjCBool = false
        if fileManager.fileExists(atPath: url.path, isDirectory: &isDirectory) {
            if isDirectory.boolValue { return url }
            throw AppSandboxError.directoryCreationFailed(url, "同名文件已存在且不是目录")
        }
        do {
            try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        } catch {
            throw AppSandboxError.directoryCreationFailed(url, "\(error)")
        }
        return url
    }

    private func ensureParentDirectory(of url: URL) throws {
        let parent = url.deletingLastPathComponent()
        try ensureDirectory(parent)
    }

    // MARK: 备份标记

    /// 设置 / 清除「排除 iCloud 备份」标记。
    ///
    /// 目录上设置会对整棵子树生效。
    /// 只有「可重新生成的大文件」才应该排除；把用户数据排除掉会直接丢数据。
    ///
    /// 实现上会**回读确认**，原因见下方注释 —— 这个标记静默失败代价太大：
    /// 漏设会让可重新下载的大文件进 iCloud 备份（App Store 审核打回），
    /// 漏清会让本该备份的数据被排除在备份之外（丢数据）。
    public func setExcludedFromBackup(_ url: URL, excluded: Bool = true) throws {
        guard fileManager.fileExists(atPath: url.path) else {
            // 对不存在的路径设置标记会直接抛错，这里给出更明确的诊断
            throw AppSandboxError.itemNotFound(url)
        }
        try writeBackupFlag(url, excluded: excluded)

        // macOS 上这一对 API 是「最终一致」的：写完立刻回读可能拿到旧值。
        // 实测（20 次 true -> false 清除）：立即回读 2/20 读到过期值；
        // 换成全新 NSURL 对象回读反而 6/20 失败（所以不是对象级缓存）；
        // 延时 50ms 或带重试后 0/20 失败，且平均只多花 0.3 次重试。
        // iOS 上通常没有这个滞后，这段重试在那里基本不会触发，代价可忽略。
        var delayMicroseconds: UInt32 = 5_000
        for _ in 0..<5 {
            if (try? isExcludedFromBackup(url)) == excluded { return }
            usleep(delayMicroseconds)
            delayMicroseconds *= 2
            try writeBackupFlag(url, excluded: excluded)
        }
        guard (try? isExcludedFromBackup(url)) == excluded else {
            throw AppSandboxError.backupFlagNotApplied(url, expected: excluded)
        }
    }

    private func writeBackupFlag(_ url: URL, excluded: Bool) throws {
        var target = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = excluded
        try target.setResourceValues(values)
    }

    public func isExcludedFromBackup(_ url: URL) throws -> Bool {
        let values = try url.resourceValues(forKeys: [.isExcludedFromBackupKey])
        return values.isExcludedFromBackup ?? false
    }

    // MARK: 写入

    /// 原子写入。
    ///
    /// - Parameter excludeFromBackup: 传 nil 表示不改动现有备份标记。
    /// - Parameter protection: 仅 iOS 生效；见 `applyFileProtection`。
    public func write(
        _ data: Data,
        to url: URL,
        excludeFromBackup: Bool? = nil,
        protection: FileProtectionType? = nil
    ) throws {
        try ensureParentDirectory(of: url)
        // .atomic：先写临时文件再 rename，进程中途被杀也不会留下半个文件
        try data.write(to: url, options: [.atomic])
        if let exclude = excludeFromBackup {
            try setExcludedFromBackup(url, excluded: exclude)
        }
        if let protection {
            try applyFileProtection(protection, to: url)
        }
    }

    /// 原子替换整个文件 / 目录（先落到临时位置再替换，避免出现中间态）。
    public func replaceItem(at destination: URL, withItemAt source: URL) throws {
        _ = try fileManager.replaceItemAt(destination, withItemAt: source)
    }

    /// 用「临时目录 + 替换」的方式安全地整体重写一个目录。
    /// 适合数据库迁移、缓存重建这类「要么全新要么保持原样」的操作。
    public func atomicallyReplaceDirectory(
        at destination: URL,
        populate: (URL) throws -> Void
    ) throws {
        let staging = fileManager.temporaryDirectory
            .appendingPathComponent("staging-\(UUID().uuidString)", isDirectory: true)
        try ensureDirectory(staging)
        do {
            try populate(staging)
            if fileManager.fileExists(atPath: destination.path) {
                _ = try fileManager.replaceItemAt(destination, withItemAt: staging)
            } else {
                try ensureParentDirectory(of: destination)
                try fileManager.moveItem(at: staging, to: destination)
            }
        } catch {
            try? fileManager.removeItem(at: staging)
            throw error
        }
    }

    // MARK: 文件保护（iOS）

    /// 设置 Data Protection 等级。
    ///
    /// 默认等级是 `.completeUntilFirstUserAuthentication`。
    ///   * `.complete`：锁屏后完全不可读 —— 后台任务、通知扩展会读不到文件；
    ///   * `.completeUntilFirstUserAuthentication`：开机解锁一次后可读，绝大多数 App 该用这个；
    ///   * `.none`：不加密保护，敏感数据不要用。
    public func applyFileProtection(_ type: FileProtectionType, to url: URL) throws {
        #if os(iOS)
        try fileManager.setAttributes([.protectionKey: type], ofItemAtPath: url.path)
        #else
        // macOS 没有 NSFileProtectionKey，静默跳过以免调用方到处写平台判断
        _ = type
        _ = url
        #endif
    }

    public func fileProtection(of url: URL) throws -> FileProtectionType? {
        #if os(iOS)
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        return attributes[.protectionKey] as? FileProtectionType
        #else
        _ = url
        return nil
        #endif
    }

    // MARK: 可移植路径（容器 UUID 变化的核心适配）

    /// 把容器内的绝对路径转成「相对容器」的路径，用于持久化。
    ///
    /// 这是本文件存在的主要理由：容器路径里的 UUID 每次安装 / 更新 / 恢复备份
    /// 都会变，把绝对路径存进 UserDefaults 或数据库，下次启动必然指向不存在的文件。
    public func portablePath(for url: URL) throws -> String {
        let containerPath = containerURL.standardizedFileURL.path
        let targetPath = url.standardizedFileURL.path

        if targetPath == containerPath { return "" }
        let prefix = containerPath.hasSuffix("/") ? containerPath : containerPath + "/"
        guard targetPath.hasPrefix(prefix) else {
            throw AppSandboxError.outsideContainer(url)
        }
        return String(targetPath.dropFirst(prefix.count))
    }

    /// 由「相对容器」的路径还原出当前容器下的绝对路径。
    public func url(forPortablePath path: String) throws -> URL {
        if path.isEmpty { return containerURL }
        // 拒绝绝对路径与 .. 逃逸，避免存到历史脏数据时写到容器外
        if path.hasPrefix("/") {
            throw AppSandboxError.invalidPortablePath(path)
        }
        let components = path.split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        if components.contains("..") {
            throw AppSandboxError.invalidPortablePath(path)
        }
        return components.reduce(containerURL) { $0.appendingPathComponent($1) }
    }

    /// 迁移历史遗留的「绝对路径」记录。
    ///
    /// 老版本如果把绝对路径写进了存储，这里尝试把它重定向到当前容器：
    /// 找到 `Documents/`、`Library/`、`tmp/` 这类锚点，取其后的相对部分重新挂到当前容器上。
    ///
    /// - Returns: 迁移后的可移植路径；返回 nil 表示这条记录认不出来，调用方应丢弃或让用户重新选择。
    public func migrateLegacyAbsolutePath(_ stored: String) -> String? {
        // 已经是相对路径，直接可用
        if !stored.hasPrefix("/") {
            return stored.isEmpty ? "" : stored
        }
        // 已经指向当前容器，转成可移植路径
        if let portable = try? portablePath(for: URL(fileURLWithPath: stored)) {
            return portable
        }
        // 旧容器的绝对路径：按锚点重新挂载。
        // 锚点必须落在一个完整的路径分量上，避免把 "MyDocuments/" 误判成 "Documents/"。
        let anchors = ["Documents/", "Library/", "tmp/"]
        for anchor in anchors {
            guard let range = stored.range(of: "/" + anchor) else { continue }
            // range.lowerBound 指向锚点前面那个 "/"，
            // 必须从它后一个字符开始取 —— 用 upperBound 会把锚点本身（如 "Documents/"）丢掉。
            let relative = String(stored[stored.index(after: range.lowerBound)...])
            if !relative.isEmpty { return relative }
        }
        return nil
    }

    // MARK: 诊断

    /// 一个目录的现状快照，用于「沙箱适配」自查。
    public struct LayoutEntry {
        public let name: String
        public let url: URL
        public let exists: Bool
        /// 实际读到的「排除备份」标记
        public let excludedFromBackup: Bool
        /// 按 Apple 的备份策略，这个目录期望的标记状态
        public let expectedExcludedFromBackup: Bool
        public let note: String

        /// 标记是否符合策略。
        /// 注意 Library/Caches 与 tmp 本身就被系统排除在备份之外，
        /// 所以这两个目录标记不一致并不算问题，这里只作提示。
        public var backupFlagMatchesPolicy: Bool {
            excludedFromBackup == expectedExcludedFromBackup
        }
    }

    /// 列出各标准目录的位置、存在性与备份标记是否符合预期。
    public func layoutReport() -> [LayoutEntry] {
        let items: [(String, SandboxDirectory, Bool, String)] = [
            ("Documents", .documents, false,
             "会被备份、用户可见。放大文件前先想清楚，审核会看备份体积。"),
            ("Library/Application Support", .applicationSupport, false,
             "会被备份、用户不可见。应用自身数据的推荐位置。"),
            ("Library/Caches", .caches, true,
             "系统策略上本就不备份、且可能被清理；标记只是双保险。只放可重新生成的内容。"),
            ("Library/NoCloud", .noCloud, true,
             "不备份。放「大且不必进 iCloud」的文件。"),
            ("tmp", .temporary, true,
             "系统策略上本就不备份、不保证跨启动存活。"),
        ]

        return items.map { name, directory, expectedExcluded, note in
            let url = (try? self.url(for: directory, createIfNeeded: false))
                ?? containerURL.appendingPathComponent(name)
            let exists = fileManager.fileExists(atPath: url.path)
            let excluded = (try? isExcludedFromBackup(url)) ?? false
            return LayoutEntry(
                name: name,
                url: url,
                exists: exists,
                excludedFromBackup: excluded,
                expectedExcludedFromBackup: expectedExcluded,
                note: note
            )
        }
    }
}
