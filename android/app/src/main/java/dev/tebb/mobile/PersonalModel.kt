package dev.tebb.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.net.URL
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection

/** 配对授权后加密保存当前模型配置。请求直接发往该服务，电脑离线时沿用上次获准的配置。 */
internal object PersonalModel {
    private const val alias = "tebb.mobile.personal-model"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance("AES", "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    /** 每个账号和配对设备独立绑定密文；电脑撤销共享后删除本地副本。 */
    @Synchronized
    fun sync(context: Context, device: String, config: String?) {
        val prefs = context.getSharedPreferences("windows_pairing", Context.MODE_PRIVATE)
        if (PairingClient.approved(context)?.pairedId != device) return
        if (config == null) {
            prefs.edit().remove("model_cipher").apply()
            return
        }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD((MobileAccount.owner + "/" + device).toByteArray())
        prefs.edit().putString("model_cipher", Base64.encodeToString(cipher.iv + cipher.doFinal(config.toByteArray()), Base64.NO_WRAP)).apply()
    }

    /** 仅将普通主聊上下文提交到已授权地址。凭据不写入历史，重定向和无完整回答的响应视为失败。 */
    fun answer(context: Context, owner: String, text: String, history: List<ChatMessage>): String {
        val device = PairingClient.approved(context)?.pairedId ?: error("请先配对电脑并共享模型")
        val saved = context.getSharedPreferences("windows_pairing", Context.MODE_PRIVATE).getString("model_cipher", null)
            ?: error("请在电脑的 Android 手机配对设置中共享 HTTPS 模型")
        val bytes = Base64.decode(saved, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, 12))
        cipher.updateAAD((owner + "/" + device).toByteArray())
        val config = JSONObject(String(cipher.doFinal(bytes, 12, bytes.size - 12), Charsets.UTF_8))
        val url = URL(config.getString("base_url").trimEnd('/') + "/chat/completions")
        require(url.protocol == "https" && url.userInfo == null && url.query == null && url.ref == null)
        val messages = JSONArray()
        history.filter { it.target == null && it.source.isNotEmpty() }.takeLast(16).forEach {
            messages.put(JSONObject().put("role", if (it.fromTebb) "assistant" else "user").put("content", it.text))
        }
        messages.put(JSONObject().put("role", "user").put("content", text))
        val body = JSONObject().put("model", config.getString("model")).put("messages", messages)
        val connection = url.openConnection() as HttpsURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10000
            connection.readTimeout = 90000
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Authorization", "Bearer " + config.getString("api_key"))
            connection.outputStream.use { it.write(body.toString().toByteArray()) }
            check(connection.responseCode in 200..299) { "模型服务返回 HTTP ${connection.responseCode}" }
            val choice = JSONObject(connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() })
                .getJSONArray("choices").getJSONObject(0)
            check(MobileAccount.owner == owner && PairingClient.approved(context)?.pairedId == device) { "账号或配对已变化" }
            check(choice.optString("finish_reason") == "stop") { "模型回复未完成" }
            val content = choice.getJSONObject("message").opt("content") as? String
            return content?.trim()?.takeIf { it.isNotEmpty() } ?: error("模型回复为空")
        } finally {
            connection.disconnect()
        }
    }
}
