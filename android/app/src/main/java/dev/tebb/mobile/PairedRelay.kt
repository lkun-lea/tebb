package dev.tebb.mobile

import android.util.Base64
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** 用配对时取得的随机凭据派生独立密钥，将设备和流向绑定到认证标签。 */
internal fun relayCipher(mode: Int, access: String, device: String, nonce: ByteArray, stream: String): Cipher {
    val key = SecretKeySpec(MessageDigest.getInstance("SHA-256")
        .digest(("tebb-relay-v1:" + access).toByteArray(Charsets.UTF_8)), "AES")
    return Cipher.getInstance("AES/GCM/NoPadding").apply {
        init(mode, key, GCMParameterSpec(128, nonce))
        updateAAD("tebb-v1/$device/$stream".toByteArray(Charsets.UTF_8))
    }
}

/** 配对和账号校验完成后，只有两端能解密对应方向的短时快照。 */
internal class PairedRelay(private val invite: JSONObject) {
    private val owner = invite.getString("owner")
    private val device = invite.getString("id")
    /** 检查密文内的设备和时间。读不到新快照时由界面显示上次已核对时间。 */
    fun snapshot(): JSONObject {
        val response = request("device-snapshot?device=$device&stream=windows")
        check(!response.isNull("sealed")) { "等待电脑上线" }
        val raw = Base64.decode(response.getString("sealed"), Base64.DEFAULT)
        require(raw.size >= 28)
        val plain = relayCipher(Cipher.DECRYPT_MODE, invite.getString("access"), device, raw.copyOfRange(0, 12), "windows").doFinal(raw, 12, raw.size - 12)
        val result = JSONObject(String(plain, Charsets.UTF_8))
        check(result.getString("device") == device && System.currentTimeMillis()/1000 - result.getLong("time") in -5L..40L)
        return result
    }

    /** 在新鲜的 Windows 快照中核对原问题，用户按下发送后才发布，等候同一请求的桌面回执。 */
    fun submit(action: String, body: JSONObject): JSONObject {
        val identity = org.json.JSONArray().put(device).put(action).put(body.getString("run")).put(body.getString("version"))
            .put(body.getString("conversation")).put(body.optString("text")).put(body.optLong("until"))
        val id = UUID.nameUUIDFromBytes(identity.toString().toByteArray(Charsets.UTF_8)).toString()
        val state = snapshot()
        val prior = state.optJSONObject("ack")
        if (prior?.optString("id") == id && !prior.has("error")) return prior
        val rows = state.getJSONArray("questions")
        check((0 until rows.length()).any { index ->
            val row = rows.getJSONObject(index)
            listOf("run","conversation","version").all { field -> row.getString(field) == body.getString(field) }
        }) { "原问题已变化，请刷新" }
        return publish(action, id, body)
    }

    /** 新增操作仅在桌面授权后手动提交。重试复用草稿编号并核对同一份回执。 */
    fun create(action: String, id: String, body: JSONObject): JSONObject {
        require(action in setOf("calendar.create", "note.create", "agent.request", "calendar.update", "calendar.list",
            "note.list", "knowledge.list", "automation.list"))
        val state = snapshot()
        val grants = state.optJSONArray("grants") ?: error("请先在电脑配对设置中授权")
        check((0 until grants.length()).any { grants.optString(it) == (if (action.startsWith("calendar.")) "calendar.create" else action) }) { "请先在电脑配对设置中授权" }
        return publish(action, id, body)
    }

    private fun publish(action: String, id: String, body: JSONObject): JSONObject {
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val data = body.put("action", action).put("id", id).put("time", System.currentTimeMillis()/1000)
        val sealed = nonce + relayCipher(Cipher.ENCRYPT_MODE, invite.getString("access"), device, nonce, "phone").doFinal(data.toString().toByteArray(Charsets.UTF_8))
        request("device-snapshot", JSONObject().put("device", device).put("stream", "phone")
            .put("sealed", Base64.encodeToString(sealed, Base64.NO_WRAP)))
        val deadline = android.os.SystemClock.elapsedRealtime() + 30_000
        while (android.os.SystemClock.elapsedRealtime() < deadline) {
            Thread.sleep(1250)
            val ack = snapshot().optJSONObject("ack")
            if (ack?.optString("id") == id) {
                check(!ack.has("error")) { ack.optString("error") }
                return ack
            }
        }
        error("等待 Windows 回执超时")
    }

    private fun request(path: String, body: JSONObject? = null): JSONObject {
        val connection = CloudChatClient.connect(path, owner)
        try {
            if (body != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            if (connection.responseCode in listOf(401, 403)) throw PairingAuthorizationDenied()
            check(connection.responseCode == 200) { "状态服务暂不可用" }
            return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        } finally { connection.disconnect() }
    }
}

