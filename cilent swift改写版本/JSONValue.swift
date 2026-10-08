//
//  JSONValue.swift
//  任意 JSON 值的强类型表示。
//
//  为什么需要它：client.py 里的记忆值是「任意 JSON」—— 字符串、数字、嵌套 dict、
//  list 都可能出现（`remember(agent_id, k, v)` 的 v 直接来自远端 JSON）。
//  Python 用 dict 天然承载这种动态结构；Swift 里如果退化成 [String: Any]，
//  既不是 Sendable、也不能 Codable 往返。所以把 JSON 的 6 种形态显式建模，
//  保证 pull 下来的内容 push 回去时结构等价。
//
//  编码保真说明：整数走 .int、小数走 .double。JSON 里写 1.0 时 Swift 的
//  JSONDecoder 可能解不出 Int，于是落到 .double(1.0)，重新编码会输出 1 —— 
//  JSON 语义等价，但字节不再逐字相同（仅影响这种「带小数点但为整值」的字面量）。
//

import Foundation

public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    // MARK: 解码 / 编码

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
            return
        }
        // 顺序有讲究：Bool 必须在数值前（避免 true 被当成 1），Int 必须在 Double 前。
        if let value = try? container.decode(Bool.self) {
            self = .bool(value)
            return
        }
        if let value = try? container.decode(Int.self) {
            self = .int(value)
            return
        }
        if let value = try? container.decode(Double.self) {
            self = .double(value)
            return
        }
        if let value = try? container.decode(String.self) {
            self = .string(value)
            return
        }
        if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
            return
        }
        if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
            return
        }
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "无法识别的 JSON 值")
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .int(let value): try container.encode(value)
        case .double(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    // MARK: 取值

    public var objectValue: [String: JSONValue]? {
        if case .object(let value) = self { return value }
        return nil
    }

    public var arrayValue: [JSONValue]? {
        if case .array(let value) = self { return value }
        return nil
    }

    public var stringValue: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    public var intValue: Int? {
        if case .int(let value) = self { return value }
        return nil
    }

    public var doubleValue: Double? {
        switch self {
        case .double(let value): return value
        case .int(let value): return Double(value)
        default: return nil
        }
    }

    public var boolValue: Bool? {
        if case .bool(let value) = self { return value }
        return nil
    }

    public var isNull: Bool {
        if case .null = self { return true }
        return false
    }

    // MARK: 便捷构造 / 转换

    /// 从原始 JSON 数据解析。
    public init(parsing data: Data) throws {
        self = try JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// 把任意 Encodable 转成 JSONValue（CLI 打印结果时用，避免为每种结果类型写一遍序列化）。
    public static func encoding<T: Encodable>(_ value: T) throws -> JSONValue {
        let data = try JSONEncoder().encode(value)
        return try JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// 序列化。默认排序 key + 美化，便于人读与 diff。
    public func serialized(sortedKeys: Bool = true, pretty: Bool = true) throws -> Data {
        let encoder = JSONEncoder()
        var formatting: JSONEncoder.OutputFormatting = [.withoutEscapingSlashes]
        if sortedKeys { formatting.insert(.sortedKeys) }
        if pretty { formatting.insert(.prettyPrinted) }
        encoder.outputFormatting = formatting
        return try encoder.encode(self)
    }

    /// 便于日志与 CLI 输出的字符串形式（Python 的 print(dict) 对应物）。
    public func printed(sortedKeys: Bool = true, pretty: Bool = true) -> String {
        guard let data = try? serialized(sortedKeys: sortedKeys, pretty: pretty) else {
            return "<JSONValue 序列化失败>"
        }
        return String(decoding: data, as: UTF8.self)
    }
}

extension JSONValue: ExpressibleByStringLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
}

extension JSONValue: CustomStringConvertible {
    public var description: String { printed(pretty: false) }
}
