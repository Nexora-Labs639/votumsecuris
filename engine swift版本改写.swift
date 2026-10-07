//
//  SandboxPolicyEngine.swift
//  策略引擎的 iOS 沙箱适配层 —— 把 AppSandbox.swift 和 PolicyEngine.swift 接起来。
//
//  为什么要这一层：PolicyEngine 只认「路径字符串」，而 iOS 上路径有两种形态，
//  直接喂给引擎会得出错误判决：
//    * 容器绝对路径（/var/mobile/Containers/Data/Application/<UUID>/...）里带 UUID，
//      而且落在 /var 下 —— 会被 FORBIDDEN_DIRS 的 "/var" 误判成系统目录。
//    * 可移植路径（Documents/x.tmp，相对容器）在引擎看来只是一个普通相对路径，
//      引擎无法知道它有没有逃出容器（"../../etc/passwd"）。
//
//  所以本层的职责只有一件事：先做「路径收敛」，再做「容器级护栏」，
//  最后才把收敛后的容器内相对路径交给 PolicyEngine 走原来的分级规则。
//  判决顺序（先命中先返回）：
//      0. AppSandboxError -> 判决（非法可移植路径 / 容器外 / 解析失败一律 deny）
//      1. 容器根、App Group 根        -> deny
//      2. 系统目录（含旧容器路径豁免）-> deny（由 PolicyEngine 的硬规则 1 给出文案）
//      3. 受保护的整目录删除          -> deny / require_approval / allow（见 protectedPaths）
//      4. 其余交给 PolicyEngine        -> 垃圾放行 / 重要文件强审批 / 其余审批
//

import Foundation

// MARK: - 收敛结果

/// 路径收敛的结果。用专门的枚举而不是 `Result`，因为失败侧是「一条判决」而不是 `Error`。
public enum SandboxPathResolution: Equatable, Sendable {
    case resolved(SandboxTarget)
    case denied(PolicyVerdict)
}

/// 收敛后的目标：一条「站在策略视角」的容器内路径。
public struct SandboxTarget: Equatable, Sendable {

    public enum Kind: Equatable, Sendable {
        /// 应用自己的容器（<container>/Documents、Library、tmp）。
        case appContainer
        /// App Group 共享容器（主 App 与 Widget / Extension 交换数据用）。
        case appGroup(identifier: String)
    }

    public let kind: Kind
    /// 交给 PolicyEngine 的路径。
    ///
    /// 应用容器内就是 `AppSandbox.portablePath` 的结果；App Group 内会加上
    /// `AppGroup/<id>/` 前缀 —— 这个前缀是本层发明的，只用于策略判定与日志，
    /// **不能**回传给 `AppSandbox.url(forPortablePath:)`。
    public let policyPath: String
    /// 收敛后的绝对路径。注意 App Group 目标下它指向 Group 容器，不属于 App 容器。
    public let url: URL
    /// 输入是不是绝对路径（诊断用）。
    public let wasAbsolute: Bool

    /// 相对「所属容器根」的路径，用于受保护目录表匹配（去掉 App Group 前缀）。
    public var pathWithinOwningContainer: String {
        switch kind {
        case .appContainer:
            return policyPath
        case .appGroup(let identifier):
            let prefix = SandboxPolicyEngine.appGroupPolicyPrefix(identifier)
            return policyPath.hasPrefix(prefix) ? String(policyPath.dropFirst(prefix.count)) : policyPath
        }
    }
}

// MARK: - 受保护的整目录

/// 「整个目录被当成一个目标删除」时的护栏。
///
/// 只在路径**正好等于**该目录时命中（最多差一个尾随 "/"）：
/// `Library/Caches` 允许整体清理，但 `Library/Caches/a.txt` 仍然走引擎的逐文件分级。
public struct ProtectedPath: Equatable, Sendable {
    /// 相对所属容器根的路径（"" 代表容器根本身）。
    public let relativePath: String
    public let action: PolicyAction
    public let severity: PolicySeverity
    public let reason: String
    public let rule: String

    public init(
        relativePath: String,
        action: PolicyAction,
        severity: PolicySeverity,
        reason: String,
        rule: String
    ) {
        self.relativePath = relativePath
        self.action = action
        self.severity = severity
        self.reason = reason
        self.rule = rule
    }

    /// 默认表。按分量数从多到少匹配，避免 "Library" 抢在 "Library/Caches" 前面。
    public static let defaults: [ProtectedPath] = [
        ProtectedPath(
            relativePath: "",
            action: .deny, severity: .critical,
            reason: "禁止操作应用容器根目录：容器路径本身就带 UUID，删掉等于把整个 App 的数据清零",
            rule: "sandbox-container-root"
        ),
        ProtectedPath(
            relativePath: "Library/Preferences",
            action: .deny, severity: .critical,
            reason: "Preferences 是 UserDefaults 的落盘位置，整体删除会连带丢设置并可能让容器元数据不一致",
            rule: "sandbox-preferences"
        ),
        ProtectedPath(
            relativePath: "Library",
            action: .deny, severity: .critical,
            reason: "Library 由系统管理（Preferences / 缓存索引 / 容器元数据），禁止整体删除",
            rule: "sandbox-library-root"
        ),
        ProtectedPath(
            relativePath: "Documents",
            action: .requireApproval, severity: .critical,
            reason: "Documents 是用户可见且会被 iCloud 备份的数据目录，整体删除前必须人工确认",
            rule: "sandbox-documents-root"
        ),
        ProtectedPath(
            relativePath: "Library/Application Support",
            action: .requireApproval, severity: .critical,
            reason: "Application Support 存放应用自身数据（数据库等），整体删除前必须人工确认",
            rule: "sandbox-application-support-root"
        ),
        ProtectedPath(
            relativePath: "Library/NoCloud",
            action: .requireApproval, severity: .critical,
            reason: "NoCloud 存放不参与 iCloud 的持久文件，整体删除前必须人工确认",
            rule: "sandbox-nocloud-root"
        ),
        ProtectedPath(
            relativePath: "Library/Caches",
            action: .allow, severity: .info,
            reason: "Caches 按 Apple 的策略本就可被系统清理、内容可重新生成，允许整体清理",
            rule: "sandbox-caches-root"
        ),
        ProtectedPath(
            relativePath: "tmp",
            action: .allow, severity: .info,
            reason: "tmp 不参与备份也不保证跨启动存活，允许整体清理",
            rule: "sandbox-tmp-root"
        ),
        ProtectedPath(
            relativePath: "Documents/Inbox",
            action: .allow, severity: .info,
            reason: "Inbox 是其它 App 投递进来的临时文件，系统不会清理，应当由本 App 用完即删",
            rule: "sandbox-inbox-root"
        ),
    ]
}

// MARK: - 适配层

public final class SandboxPolicyEngine {

    /// 沙箱路径适配层（AppSandbox.swift）。
    public let sandbox: AppSandbox
    /// 逐文件级别的策略引擎。
    public let engine: PolicyEngine
    /// 受保护的整目录表，按分量数降序排好。
    public let protectedPaths: [ProtectedPath]

    /// 已知的 App Group 容器：identifier -> 容器根 URL。
    /// 解析不出来（entitlements 没配）的直接不进表，行为等同于「这个 group 不存在」。
    public let appGroupContainers: [String: URL]

    public init(
        sandbox: AppSandbox,
        rules: PolicyRules = .standard,
        appGroupIdentifiers: [String] = [],
        protectedPaths: [ProtectedPath] = ProtectedPath.defaults
    ) {
        self.sandbox = sandbox
        self.engine = PolicyEngine(rules: rules)
        self.protectedPaths = protectedPaths.sorted {
            $0.relativePath.split(separator: "/").count > $1.relativePath.split(separator: "/").count
        }

        var groups: [String: URL] = [:]
        for identifier in appGroupIdentifiers {
            // AppSandbox 在 entitlements 缺失时抛 appGroupUnavailable；这里不抛，
            // 只是把这个 group 当作「不存在」，避免整个引擎起不来。
            if let url = try? sandbox.url(for: .appGroup(identifier: identifier), createIfNeeded: false) {
                groups[identifier] = url.standardizedFileURL
            }
        }
        self.appGroupContainers = groups
    }

    /// App Group 在策略视角下的路径前缀。
    public static func appGroupPolicyPrefix(_ identifier: String) -> String {
        "AppGroup/\(identifier)/"
    }

    // MARK: 主入口

    /// 评估一次工具调用。先收敛路径、过容器护栏，再交给 PolicyEngine。
    ///
    /// 只带 path 的工具（delete_file / write_file / 未来的 read_file 等）会走收敛；
    /// 不带 path 的工具（run_shell）原样透传。
    public func evaluate(_ call: PolicyToolCall) -> PolicyVerdict {
        let rawPath = call.params["path"] ?? ""

        guard !rawPath.isEmpty else {
            // 对应 Python 的 `path = params.get("path", "") or ""`：没有 path 就不做路径规则。
            return engine.evaluate(call)
        }

        let target: SandboxTarget
        switch resolvePath(rawPath) {
        case .denied(let verdict):
            return verdict
        case .resolved(let resolved):
            target = resolved
        }

        if let guarded = guardOwningContainer(target) {
            return guarded
        }

        var forwarded = call.params
        forwarded["path"] = target.policyPath
        return engine.evaluate(
            PolicyToolCall(tool: call.tool, params: forwarded, risk: call.risk, undo: call.undo)
        )
    }

    // MARK: 路径收敛

    /// 把任意输入路径收敛成「容器内相对路径」。
    ///
    /// 顺序很重要：
    ///   1. 已经在当前 App 容器内 -> 直接转可移植路径（当前安装的绝对路径）
    ///   2. 已经在已知 App Group 容器内 -> 加前缀
    ///   3. 系统禁删目录，且不像「容器路径」-> 交给引擎的硬规则 1 拒绝
    ///      （豁免逻辑：/var/mobile/Containers/... 和 /Library/Containers/... 的旧容器路径
    ///       会命中 "/var"、"/Library"，但它们其实是本 App 的历史路径，必须允许迁移）
    ///   4. 旧安装 / 换过 UUID 的绝对路径 -> 按锚点迁移到当前容器
    ///   5. 其它绝对路径 -> deny（不属于本 App 的容器）
    public func resolvePath(_ raw: String) -> SandboxPathResolution {
        guard !raw.isEmpty else {
            return .resolved(SandboxTarget(kind: .appContainer, policyPath: "", url: sandbox.containerURL, wasAbsolute: false))
        }

        if raw.hasPrefix("/") {
            let url = URL(fileURLWithPath: raw)

            // 1) 当前容器内
            if let portable = try? sandbox.portablePath(for: url) {
                return .resolved(
                    SandboxTarget(kind: .appContainer, policyPath: portable, url: url, wasAbsolute: true)
                )
            }

            // 2) 已知 App Group 容器内
            for (identifier, groupURL) in appGroupContainers {
                if let relative = Self.relativePath(of: url, within: groupURL) {
                    let policyPath = Self.appGroupPolicyPrefix(identifier) + relative
                    return .resolved(
                        SandboxTarget(
                            kind: .appGroup(identifier: identifier),
                            policyPath: policyPath,
                            url: url,
                            wasAbsolute: true
                        )
                    )
                }
            }

            // 3) 系统禁删目录（容器路径豁免）
            if !Self.looksLikeContainerPath(raw),
               let matched = engine.isForbidden(raw) {
                return .denied(
                    PolicyVerdict(
                        action: .deny,
                        reason: "禁止操作系统目录: \(matched)",
                        severity: .critical,
                        rule: "forbidden-dir"
                    )
                )
            }

            // 4) 旧容器的绝对路径：迁移
            if let migrated = sandbox.migrateLegacyAbsolutePath(raw) {
                if migrated.isEmpty {
                    return .denied(containerRootDenial(path: raw))
                }
                return .resolved(
                    SandboxTarget(
                        kind: .appContainer,
                        policyPath: migrated,
                        url: (try? sandbox.url(forPortablePath: migrated)) ?? url,
                        wasAbsolute: true
                    )
                )
            }

            // 5) 认不出来的绝对路径
            return .denied(
                PolicyVerdict(
                    action: .deny,
                    reason: "路径不属于当前应用容器，且无法按 Documents/Library/tmp 锚点迁移: \(raw)"
                          + "。容器路径带 UUID，很可能是旧安装或其它 App 的路径，应当让用户重新选择。",
                    severity: .critical,
                    rule: "sandbox-outside-container"
                )
            )
        }

        // 相对路径 = 可移植路径，交给 AppSandbox 校验（它会拒绝绝对路径与 ".." 逃逸）
        do {
            let url = try sandbox.url(forPortablePath: raw)
            return .resolved(
                SandboxTarget(kind: .appContainer, policyPath: raw, url: url, wasAbsolute: false)
            )
        } catch {
            return .denied(Self.verdict(for: error))
        }
    }

    // MARK: 容器护栏

    /// 容器根与受保护整目录。
    public func guardOwningContainer(_ target: SandboxTarget) -> PolicyVerdict? {
        // 先折叠 "//" 与 "\"，再剥掉前缀 "./"，否则 "./Library" 会绕过 Library 的 deny。
        // 注意：这里只影响护栏匹配；交给引擎的 policyPath 保持原样，
        // 因为引擎尾随 "/" 的语义（"a.tmp/" 的文件名视作空串）与 Python 版是对齐的。
        var relative = PolicyEngine.normalizePath(target.pathWithinOwningContainer)
        while relative.hasPrefix("./") { relative.removeFirst(2) }
        // 尾随 "/" 视作同一目录（"Library/Caches/" == "Library/Caches"）
        while relative.hasSuffix("/") { relative.removeLast() }
        if relative == "." { relative = "" }

        // App Group 容器根本身也要挡掉（表里的 "" 只覆盖 App 容器根）
        if case .appGroup(let identifier) = target.kind, relative.isEmpty {
            return PolicyVerdict(
                action: .deny,
                reason: "禁止操作 App Group 容器根目录: \(identifier)，Group 容器由系统管理且多个进程共用",
                severity: .critical,
                rule: "sandbox-appgroup-root"
            )
        }

        for entry in protectedPaths where entry.relativePath == relative {
            return PolicyVerdict(
                action: entry.action,
                reason: entry.reason,
                severity: entry.severity,
                rule: entry.rule
            )
        }
        return nil
    }

    // MARK: AppSandboxError -> 判决

    /// 把 AppSandbox 抛出的错误统一映射成「拒绝」。
    ///
    /// 这里全部按 fail-closed 处理：路径解析不出来的操作一律不放行。
    public static func verdict(for error: Error) -> PolicyVerdict {
        guard let sandboxError = error as? AppSandboxError else {
            return PolicyVerdict(
                action: .deny,
                reason: "路径解析失败，按 fail-closed 拒绝: \(error)",
                severity: .critical,
                rule: "sandbox-unresolved-path"
            )
        }

        switch sandboxError {
        case .invalidPortablePath(let path):
            return PolicyVerdict(
                action: .deny,
                reason: "非法可移植路径（绝对路径或含 .. 逃逸）: \(path)",
                severity: .critical,
                rule: "sandbox-invalid-portable-path"
            )
        case .outsideContainer(let url):
            return PolicyVerdict(
                action: .deny,
                reason: "路径不在应用容器内: \(url.path)",
                severity: .critical,
                rule: "sandbox-outside-container"
            )
        case .containerUnavailable, .appGroupUnavailable, .itemNotFound,
             .directoryCreationFailed, .backupFlagNotApplied:
            return PolicyVerdict(
                action: .deny,
                reason: "沙箱路径不可用: \(sandboxError.description)",
                severity: .critical,
                rule: "sandbox-unavailable"
            )
        }
    }

    // MARK: 工具

    private func containerRootDenial(path: String) -> PolicyVerdict {
        PolicyVerdict(
            action: .deny,
            reason: "禁止操作应用容器根目录: \(path)",
            severity: .critical,
            rule: "sandbox-container-root"
        )
    }

    /// 复刻 AppSandbox.portablePath 的算法，但基准目录可以换成 App Group 容器。
    /// （AppSandbox 的 portablePath 只以 App 容器为基准，Group 内路径需要自己的基准。）
    static func relativePath(of url: URL, within base: URL) -> String? {
        let basePath = base.standardizedFileURL.path
        let targetPath = url.standardizedFileURL.path
        if targetPath == basePath { return "" }
        let prefix = basePath.hasSuffix("/") ? basePath : basePath + "/"
        guard targetPath.hasPrefix(prefix) else { return nil }
        return String(targetPath.dropFirst(prefix.count))
    }

    /// 是不是 Apple 的容器路径。这类路径会被 FORBIDDEN_DIRS 的 /var、/Library 命中，
    /// 但它们是本 App（或本 App 历史安装）的数据，必须走迁移而不是拒绝。
    static func looksLikeContainerPath(_ path: String) -> Bool {
        let markers = [
            "/Containers/Bundle/Application/",
            "/Containers/Data/Application/",
            "/Containers/Shared/AppGroup/",
            "/Containers/Shared/Team/",
        ]
        return markers.contains { path.contains($0) }
    }
}
