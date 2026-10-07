// swift-tools-version: 6.0
//
//  AgentKit —— engine.py / client.py / rag.py 的 Swift 移植工程。
//
//  模块划分刻意与原来的 Python 文件一一对应，方便对照维护：
//      AppSandbox.swift            -> AppSandboxKit   （沙箱路径层，被下面几个模块共用）
//      engine.py                   -> PolicyEngine    （策略引擎 + 沙箱适配 + 规则库版本化）
//      client.py                   -> MemorySync      （记忆同步客户端 + 记忆存储）
//      rag.py                      -> RAG             （最简 RAG：切块 / 向量 / 检索）
//      engine.py __main__          -> policyctl       （策略自检工具）
//      client.py __main__          -> syncctl         （同步命令行）
//      rag.py __main__             -> ragctl          （知识库扫描 / 检索）
//
//  平台：iOS 16 / macOS 13。AppSandbox 的 iOS 专用分支用 #if os(iOS) 包着，
//  因此测试可以在 macOS 上跑（注入 containerURL 即可，见 AppSandbox 头注释）。
//
import PackageDescription

let package = Package(
    name: "AgentKit",
    platforms: [
        .macOS(.v13),
        .iOS(.v16),
    ],
    products: [
        .library(name: "AppSandboxKit", targets: ["AppSandboxKit"]),
        .library(name: "PolicyEngine", targets: ["PolicyEngine"]),
        .library(name: "MemorySync", targets: ["MemorySync"]),
        .library(name: "RAG", targets: ["RAG"]),
        // 调用 sandbox_runner 的客户端 + MethodChannel 载荷构造（Flutter 侧复用同一份代码）
        .library(name: "SandboxRunnerKit", targets: ["SandboxRunnerKit"]),
        .executable(name: "policyctl", targets: ["policyctl"]),
        .executable(name: "syncctl", targets: ["syncctl"]),
        .executable(name: "ragctl", targets: ["ragctl"]),
        // 带 App Sandbox entitlement 的 macOS App（用 Scripts/build-sandbox-demo.sh 组装成 .app）
        .executable(name: "SandboxDemo", targets: ["SandboxDemo"]),
        // 调 sandbox_runner（macOS版本）.py 读文件的 macOS App
        .executable(name: "SandboxRunnerDemo", targets: ["SandboxRunnerDemo"]),
    ],
    targets: [
        // iOS 沙箱路径适配层
        .target(name: "AppSandboxKit"),

        // 策略引擎。Resources/policy 就是「规则知识库」：rules.json + CHANGELOG.md
        // 一起打进 bundle，用 PolicyRulesStore 读取（见 README 的版本化流程）。
        .target(
            name: "PolicyEngine",
            dependencies: ["AppSandboxKit"],
            resources: [.copy("Resources/policy")]
        ),

        // 记忆同步客户端 + 记忆存储
        .target(
            name: "MemorySync",
            dependencies: ["AppSandboxKit"]
        ),

        // 最简 RAG（rag.py 的移植）：切块 -> ollama 取向量 -> SQLite -> 余弦检索
        .target(name: "RAG"),

        // 调 sandbox_runner 的逻辑 + 传给 Dart 的载荷结构，纯 Foundation，不依赖 Flutter。
        // 这样它既能在命令行 App 里用，也能直接被 Flutter 的 macOS Runner 链接，
        // 还能在 SwiftPM 里单测。
        .target(name: "SandboxRunnerKit"),

        // 命令行工具
        .executableTarget(
            name: "policyctl",
            dependencies: ["PolicyEngine", "AppSandboxKit"]
        ),
        .executableTarget(
            name: "syncctl",
            dependencies: ["MemorySync", "AppSandboxKit"]
        ),
        .executableTarget(
            name: "ragctl",
            dependencies: ["RAG"]
        ),
        // macOS App：点按钮 -> AppSandboxKit 读文件 -> 显示内容。
        // 它在包里的身份是可执行文件；带 entitlements 的 .app 由构建脚本组装。
        .executableTarget(
            name: "SandboxDemo",
            dependencies: ["AppSandboxKit"]
        ),
        // macOS App：点按钮 -> 起 python3 调 sandbox_runner（macOS版本）.py -> 跑三项边界检查。
        .executableTarget(
            name: "SandboxRunnerDemo",
            dependencies: ["SandboxRunnerKit"]
        ),

        // 测试
        .testTarget(
            name: "PolicyEngineTests",
            dependencies: ["PolicyEngine", "AppSandboxKit"]
        ),
        .testTarget(
            name: "MemorySyncTests",
            dependencies: ["MemorySync", "AppSandboxKit"]
        ),
        // 校验「给 Dart 的载荷」这一跨语言契约
        .testTarget(
            name: "SandboxRunnerKitTests",
            dependencies: ["SandboxRunnerKit"]
        ),
        // AppSandbox 自己的单元测试（读 / 写 / 删除闸门 / 可移植路径 / 迁移 / 备份标记）
        .testTarget(
            name: "AppSandboxKitTests",
            dependencies: ["AppSandboxKit"]
        ),
    ]
)
