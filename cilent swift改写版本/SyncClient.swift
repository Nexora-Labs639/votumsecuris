//
//  SyncClient.swift
//  同步客户端：拉取/推送其他设备的记忆。client.py 的 Swift 移植。
//
//  函数对照表：
//      ping(ip, port)                     -> ping(endpoint:timeout:)
//      pull_memory(ip, agent_id, port)    -> pullMemory(endpoint:agentID:timeout:)
//      push_memory(ip, agent_id, port)    -> pushMemory(endpoint:agentID:timeout:)
//      sync_both(ip, agent_id, port)      -> syncBoth(endpoint:agentID:timeout:)
//
//  与 client.py 的有意差异（每条都有理由，不是随手改的）：
//    1. 错误处理：Python 把异常吞掉、返回 {"error": "..."}；Swift 用 throws。
//       HTTP 状态码 Python 靠 urllib 抛 HTTPError 间接变成 error，这里显式校验
//       200..<300 —— URLSession **不会**因为 4xx/5xx 报错，不校验就会把
//       错误页当成正常响应。CLI 层再把 throws 还原成 {"error": ...} 的输出，
//       所以命令行观感与 Python 一致。
//    2. URL 拼接：Python 用 f-string 直接拼，agent id 里的特殊字符会破坏 URL；
//       这里走 URLComponents，query 自动百分号编码。
//    3. syncBoth 默认 requirePullSuccess = true：拉取失败时不再继续推送。
//       Python 会照推不误，等于用本地（可能更旧的）数据覆盖对方，是真实的数据丢失风险；
//       需要旧行为就显式传 requirePullSuccess: false。
//
//  iOS 注意：明文 http:// 受 App Transport Security 限制，真机连局域网设备需要在
//  Info.plist 里配 NSAppTransportSecurity（见 README）。用 https:// 则不受影响。
//

import Foundation

// MARK: - 错误

public enum SyncClientError: Error, CustomStringConvertible, Equatable {
    case invalidEndpoint(String)
    case transport(String)
    case unexpectedStatus(code: Int, detail: String)
    case invalidResponseBody(detail: String)
    case malformedResponse(String)
    case storeFailure(String)
    case pullFailedBeforePush(String)

    public var description: String {
        switch self {
        case .invalidEndpoint(let detail):
            return "无法构造请求地址: \(detail)"
        case .transport(let detail):
            return "网络请求失败: \(detail)"
        case .unexpectedStatus(let code, let detail):
            return "服务端返回 HTTP \(code)\(detail.isEmpty ? "" : ": \(detail)")"
        case .invalidResponseBody(let detail):
            return "响应不是合法 JSON: \(detail)"
        case .malformedResponse(let detail):
            return "响应结构不符合预期: \(detail)"
        case .storeFailure(let detail):
            return "本地记忆读写失败: \(detail)"
        case .pullFailedBeforePush(let detail):
            return "拉取失败，已跳过推送以免覆盖对方数据（需要旧行为请传 requirePullSuccess: false）: \(detail)"
        }
    }
}

// MARK: - 地址

/// 一台对端设备的地址。对应 Python 里 `f"http://{ip}:{port}"` 的拼接。
public struct SyncEndpoint: Equatable, Sendable {

    public var scheme: String
    public var host: String
    public var port: Int

    /// - Parameter host: 可以是 `192.168.1.5`、`192.168.1.5:8520`、也可以是完整前缀
    ///   `http://192.168.1.5:9000`（方便直接把用户粘贴的地址丢进来）。
    public init(host: String, port: Int = 8520, scheme: String = "http") {
        let raw = host.trimmingCharacters(in: .whitespacesAndNewlines)

        // 完整 URL 形态：以 components 为准
        if let components = URLComponents(string: raw), let parsedScheme = components.scheme,
           let parsedHost = components.host, !parsedScheme.isEmpty, !parsedHost.isEmpty {
            self.scheme = parsedScheme
            self.host = parsedHost
            self.port = components.port ?? port
            return
        }

        // "host:port" 形态：只有在一段冒号且尾部是数字时才拆，避免破坏 IPv6 字面量
        let parts = raw.split(separator: ":", omittingEmptySubsequences: false)
        if parts.count == 2, let parsedPort = Int(parts[1]), !parts[0].isEmpty {
            self.scheme = scheme
            self.host = String(parts[0])
            self.port = parsedPort
            return
        }

        self.scheme = scheme
        self.host = raw
        self.port = port
    }

    /// 拼出 `scheme://host:port/path?query`。
    public func url(path: String, query: [URLQueryItem] = []) throws -> URL {
        var components = URLComponents()
        components.scheme = scheme
        components.host = host
        components.port = port
        components.path = path.hasPrefix("/") ? path : "/" + path
        if !query.isEmpty {
            components.queryItems = query
        }
        guard let url = components.url else {
            throw SyncClientError.invalidEndpoint("host=\(host) port=\(port) path=\(path)")
        }
        return url
    }

    public var displayName: String { "\(host):\(port)" }
}

// MARK: - HTTP 层

/// 只负责「发请求、校验状态码、解 JSON」。
public struct SyncHTTPClient {

    public var session: URLSession
    public var defaultTimeout: TimeInterval

    /// 默认会话：**禁用缓存**。
    ///
    /// Python 的 urllib 不做任何缓存，每次都是真实请求；而 URLSession 默认带
    /// 磁盘 + 内存缓存，会把 GET /memory、GET /ping 的响应缓存下来 —— 那意味着
    /// 「同步成功」但拿到的可能是几分钟前的旧记忆，甚至在被缓存的 /ping 上误判设备在线。
    /// 所以这里用 ephemeral（不落盘）+ reloadIgnoringLocalCacheData（不读缓存）。
    public static let uncachedSession: URLSession = URLSession(configuration: uncachedConfiguration)

    public static var uncachedConfiguration: URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 5
        configuration.timeoutIntervalForResource = 30
        configuration.waitsForConnectivity = false
        return configuration
    }

    public init(session: URLSession = SyncHTTPClient.uncachedSession, defaultTimeout: TimeInterval = 5) {
        self.session = session
        self.defaultTimeout = defaultTimeout
    }

    public func getJSON(_ url: URL, timeout: TimeInterval? = nil) async throws -> JSONValue {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        return try await send(request, timeout: timeout)
    }

    public func postJSON(_ url: URL, body: JSONValue, timeout: TimeInterval? = nil) async throws -> JSONValue {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            request.httpBody = try body.serialized(sortedKeys: false, pretty: false)
        } catch {
            throw SyncClientError.invalidResponseBody(detail: "请求体序列化失败: \(error)")
        }
        return try await send(request, timeout: timeout)
    }

    private func send(_ request: URLRequest, timeout: TimeInterval?) async throws -> JSONValue {
        var request = request
        request.timeoutInterval = timeout ?? defaultTimeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        // 双保险：即使调用方传进来的是带缓存的 session，这条请求也不读缓存
        request.cachePolicy = .reloadIgnoringLocalCacheData

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw SyncClientError.transport("\(error)")
        }

        // URLSession 对 4xx/5xx 不报错，必须自己校验，否则错误页会被当成正常响应。
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw SyncClientError.unexpectedStatus(code: http.statusCode, detail: Self.snippet(data))
        }

        do {
            return try JSONValue(parsing: data)
        } catch {
            throw SyncClientError.invalidResponseBody(detail: "前 \(Self.snippetLimit) 字节: \(Self.snippet(data))")
        }
    }

    private static let snippetLimit = 200

    /// 截断响应体，避免把巨大错误页塞进日志/异常里。
    static func snippet(_ data: Data) -> String {
        let prefix = data.prefix(snippetLimit)
        let text = String(decoding: prefix, as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return data.count > snippetLimit ? text + "…" : text
    }
}

// MARK: - 结果

/// 对应 Python 的 `{"ok": True, "pulled": n, "from": ip}`。
public struct PullResult: Codable, Equatable, Sendable {
    public let ok: Bool
    /// 远端返回的 key 数量（不是「新增」数量）—— 与 Python 的 `len(remote)` 一致。
    public let pulled: Int
    public let from: String

    public init(ok: Bool, pulled: Int, from: String) {
        self.ok = ok
        self.pulled = pulled
        self.from = from
    }
}

/// 对应 Python 的 `{"pull": <pull>, "push": <push>}`。
public struct SyncResult: Codable, Equatable, Sendable {
    public let pull: PullResult
    public let push: JSONValue

    public init(pull: PullResult, push: JSONValue) {
        self.pull = pull
        self.push = push
    }
}

// MARK: - 客户端

public final class MemorySyncClient {

    public let store: MemoryStore
    public let http: SyncHTTPClient

    public init(store: MemoryStore, http: SyncHTTPClient = SyncHTTPClient()) {
        self.store = store
        self.http = http
    }

    /// GET /ping —— 对应 `ping(ip, port)`。
    public func ping(endpoint: SyncEndpoint, timeout: TimeInterval? = nil) async throws -> JSONValue {
        try await http.getJSON(try endpoint.url(path: "/ping"), timeout: timeout)
    }

    /// 从远端拉取记忆并合并进本地 —— 对应 `pull_memory(ip, agent_id, port)`。
    ///
    /// 合并语义与 Python 一致：只增改远端带回来的 key，本地其它 key 保持不动。
    public func pullMemory(
        endpoint: SyncEndpoint,
        agentID: String,
        timeout: TimeInterval? = nil
    ) async throws -> PullResult {
        let url = try endpoint.url(path: "/memory", query: [URLQueryItem(name: "agent", value: agentID)])
        let response = try await http.getJSON(url, timeout: timeout)

        guard let object = response.objectValue else {
            throw SyncClientError.malformedResponse("顶层不是 JSON 对象")
        }

        // Python: remote = data.get("memories", {}) —— 缺字段按空处理，不算错误。
        var remote: [String: JSONValue] = [:]
        if let memories = object["memories"] {
            guard let parsed = memories.objectValue else {
                throw SyncClientError.malformedResponse("\"memories\" 不是 JSON 对象")
            }
            remote = parsed
        }

        do {
            try store.rememberAll(agentID: agentID, values: remote)
        } catch {
            throw SyncClientError.storeFailure("\(error)")
        }

        return PullResult(ok: true, pulled: remote.count, from: endpoint.host)
    }

    /// 把本地记忆推给远端 —— 对应 `push_memory(ip, agent_id, port)`。
    /// 返回值是服务端的响应体（Python 直接把 `_http_post` 的结果返回）。
    public func pushMemory(
        endpoint: SyncEndpoint,
        agentID: String,
        timeout: TimeInterval? = nil
    ) async throws -> JSONValue {
        let local: [String: JSONValue]
        do {
            local = try store.allMemories(agentID: agentID)
        } catch {
            throw SyncClientError.storeFailure("\(error)")
        }

        let body = JSONValue.object([
            "agent": .string(agentID),
            "memories": .object(local),
        ])
        return try await http.postJSON(try endpoint.url(path: "/memory"), body: body, timeout: timeout)
    }

    /// 双向同步 —— 对应 `sync_both(ip, agent_id, port)`。
    ///
    /// - Parameter requirePullSuccess: 默认 true。拉取失败就抛错、不推送。
    ///   传 false 可恢复 client.py 的旧行为（拉取失败仍然推送），但那可能用本地旧数据覆盖对方，
    ///   除非你明确知道自己在做什么，否则不要关。
    public func syncBoth(
        endpoint: SyncEndpoint,
        agentID: String = "agent-A",
        timeout: TimeInterval? = nil,
        requirePullSuccess: Bool = true
    ) async throws -> SyncResult {
        let pull: PullResult
        do {
            pull = try await pullMemory(endpoint: endpoint, agentID: agentID, timeout: timeout)
        } catch {
            if requirePullSuccess {
                throw SyncClientError.pullFailedBeforePush("\(error)")
            }
            // 旧行为：继续推送，用一个「拉取失败」的占位结果代替 pull
            pull = PullResult(ok: false, pulled: 0, from: endpoint.host)
        }

        let push = try await pushMemory(endpoint: endpoint, agentID: agentID, timeout: timeout)
        return SyncResult(pull: pull, push: push)
    }
}
