import Foundation
import Vision
import ImageIO

// Input paths are local validated assets; this helper performs no networking.
do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "arguments", code: 1) }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]), options: [:])
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let data = try JSONSerialization.data(withJSONObject: ["text": lines.joined(separator: "\n")])
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data("Vision OCR failed\n".utf8))
    exit(1)
}
