package dev.tebb.mobile

import org.json.JSONObject
import java.net.URL
import javax.net.ssl.HttpsURLConnection

/** 云端已确认任务终止，此时再次发送应创建新的请求。 */
internal class CloudTaskEnded(message: String) : Exception(message)

/** 手机直接访问个人 ECS，原请求编号用于断线重试时找回同一任务。 */
internal object CloudChatClient {
    /** 令牌仅发送给固定服务地址，禁止重定向到其他主机。 */
    internal fun connect(path: String, owner: String) =
        (URL("https://8.136.145.17/cloud/v1/$path").openConnection() as HttpsURLConnection).apply {
            instanceFollowRedirects = false
            connectTimeout = 8000
            readTimeout = 25000
            setRequestProperty("Authorization", "Bearer " + MobileAccount.cloudToken(owner))
        }

    /**
     * 提交消息并按回执监听同一任务。队列与生成状态交给界面显示，终态决定能否复用请求编号。
     * @param onProgress 收到排队或运行事件时回到调用方更新提示。
     */
    suspend fun answer(owner: String, id: String, text: String, onProgress: suspend (ChatWork) -> Unit): String {
        val post = connect("messages", owner)
        val run = try {
            post.requestMethod = "POST"
            post.doOutput = true
            post.setRequestProperty("Content-Type", "application/json")
            val body = JSONObject().put("conversation", "mobile-main").put("request_id", id).put("text", text)
            post.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            check(post.responseCode == 200) { "提交失败（HTTP ${post.responseCode}）" }
            JSONObject(post.inputStream.bufferedReader().use { it.readText() }).getString("run_id")
        } finally { post.disconnect() }
        val events = connect("events?conversation=mobile-main", owner)
        try {
            check(events.responseCode == 200) { "读取回答失败（HTTP ${events.responseCode}）" }
            events.inputStream.bufferedReader().useLines { lines ->
                for (line in lines) {
                    if (!line.startsWith("data:")) continue
                    val event = JSONObject(line.substringAfter(':'))
                    val row = event.optJSONObject("data") ?: continue
                    if (row.optString("id") != run) continue
                    when (row.optString("state")) {
                        "queued" -> onProgress(ChatWork.Queued)
                        "running" -> onProgress(ChatWork.Answering)
                        "succeeded" -> return row.getString("answer")
                        "failed", "cancelled", "interrupted", "timed_out" -> throw CloudTaskEnded(row.optString("error", "云端任务结束"))
                    }
                }
            }
            error("连接已结束，可重试读取原任务")
        } finally { events.disconnect() }
    }
}
