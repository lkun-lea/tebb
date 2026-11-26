package dev.tebb.mobile

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.net.Proxy
import java.net.URL
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** 电脑拒绝当前账号或设备凭据时，主聊天立即移除旧任务快照。 */
internal class PairingAuthorizationDenied : IllegalStateException("Windows 授权无效，请检查账号和配对状态")

/** 本轮配对的连接信息。二维码中的证书指纹只用于验证提供该二维码的 Windows 服务。 */
internal class PairingClient(private val invite: JSONObject) {
    private val relay = if (invite.optBoolean("relay")) PairedRelay(invite) else null
    val usesRelay: Boolean get() = relay != null
    private val owner = invite.getString("owner")
    private val host = invite.getString("host")
    private val port = invite.getInt("port")
    private val pin = invite.getString("pin")

    init {
        val ip = host.split('.').map { it.toIntOrNull() }
        require(invite.getInt("v") == 2 && ip.size == 4 && ip.all { it != null && it in 0..255 } &&
            (ip[0] == 10 || ip[0] == 192 && ip[1] == 168 || ip[0] == 172 && ip[1] in 16..31) &&
            port in 1..65535 && pin.matches(Regex("[0-9a-f]{64}"))) { "无效的局域网配对码" }
    }

    /** 用 Android Keystore 中的设备私钥签署一次性凭据，Windows 只接收公钥和签名。 */
    fun apply(): JSONObject {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val alias = "tebb.mobile.pairing"
        if (!store.containsAlias(alias)) {
            val generator = KeyPairGenerator.getInstance("EC", "AndroidKeyStore")
            generator.initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")).setDigests(KeyProperties.DIGEST_SHA256).build())
            generator.generateKeyPair()
        }
        val token = invite.getString("token")
        require(token.matches(Regex("[A-Za-z0-9_-]{43}")))
        val signer = Signature.getInstance("SHA256withECDSA")
        signer.initSign(store.getKey(alias, null) as PrivateKey)
        signer.update(("tebb-pair-v1:" + token).toByteArray(Charsets.UTF_8))
        val body = JSONObject().put("token", token).put("name", Build.MODEL.take(100))
            .put("public_key", Base64.encodeToString(store.getCertificate(alias).publicKey.encoded, Base64.NO_WRAP))
            .put("signature", Base64.encodeToString(signer.sign(), Base64.NO_WRAP))
        return request("/pairings", body = body)
    }

    /** 只持有本次申请回执的手机能查询电脑决定；此凭据不会出现在 URL 中。 */
    fun status(receipt: JSONObject): JSONObject =
        request("/pairings/" + receipt.getString("id"), ticket = receipt.getString("ticket"))

    /** 读取当前设备经电脑批准可见的待答快照，保留原运行、会话和问题版本。 */
    fun snapshot(): DeviceSnapshot {
        val raw = relay?.snapshot() ?: request("/questions", ticket = invite.getString("access"))
        return DeviceSnapshot(raw.optLong("time", System.currentTimeMillis()/1000) * 1000,
            decodeQuestions(raw.getJSONArray("questions")), raw.optJSONArray("history")?.toString() ?: "[]")

    }

    private fun decodeQuestions(rows: org.json.JSONArray): List<PendingQuestion> {
        return List(rows.length()) { index ->
            val row = rows.getJSONObject(index)
            PendingQuestion(QuestionKey(row.getString("run"), row.getString("version")), row.getString("title"),
                row.getString("prompt"), row.getString("conversation"), invite.getString("id"), row.optLong("created"),
                row.optJSONArray("items")?.let { items -> (0 until items.length()).joinToString(" · ") { i ->
                    val item = items.getJSONObject(i)
                    listOf(item.optString("owner"),item.optString("due")).filter { it.isNotBlank() }.joinToString(" · ")
                } } ?: row.optString("item_label"), row.optLong("asked"))
        }
    }

    /** 仅恢复当前账号与配对设备上次获准读取的快照；撤权后清理。 */
    fun cached(context: Context): DeviceSnapshot? {
        val raw = preferences(context).getString("question_cache", null) ?: return null
        val saved = JSONObject(raw)
        if (saved.optString("owner") != owner || saved.optString("device") != invite.getString("id")) return null
        if (System.currentTimeMillis() - saved.getLong("time") > 7L * 86400 * 1000) {
            clearCache(context)
            return null
        }
        return DeviceSnapshot(saved.getLong("time"), decodeQuestions(saved.getJSONArray("rows")), saved.optString("history","[]"))
    }

    /** 把快照和来源时间作为一个值替换，避免跨设备混用旧行。 */
    fun cache(context: Context, snapshot: DeviceSnapshot) {
        val data = org.json.JSONArray()
        snapshot.rows.forEach { data.put(JSONObject().put("run", it.key.runId).put("version", it.key.version)
            .put("asked", it.asked).put("item_label", it.items).put("created", it.created).put("title", it.title).put("prompt", it.prompt).put("conversation", it.conversation)) }
        preferences(context).edit().putString("question_cache", JSONObject().put("owner", owner)
            .put("device", invite.getString("id")).put("time", snapshot.time).put("history",snapshot.history).put("rows", data).toString()).apply()
    }

    fun clearCache(context: Context) = preferences(context).edit().remove("question_cache").apply()

    private fun preferences(context: Context) = context.getSharedPreferences("windows_pairing", Context.MODE_PRIVATE)

    /** 延后同一版本的待答提醒，回执必须对应请求的时间与原运行。 */
    fun defer(question: PendingQuestion, until: Long) {
        check(question.deviceId == invite.getString("id"))
        val body = JSONObject().put("conversation", question.conversation).put("run", question.key.runId)
            .put("version", question.key.version).put("until", until)
        val ack = relay?.submit("defer", body) ?: request("/defer", body, invite.getString("access"))
        check(ack.getString("run") == question.key.runId && ack.getString("version") == question.key.version &&
            ack.getLong("until") == until) { "改期回执不匹配" }
    }

    /** 将编辑后的文字送回配对时的电脑，并核对 Windows 返回的原任务回执。 */
    fun answer(question: PendingQuestion, text: String) {
        check(question.deviceId == invite.getString("id")) { "回复目标属于另一台已配对设备" }
        val body = JSONObject().put("run", question.key.runId).put("version", question.key.version)
            .put("conversation", question.conversation).put("text", text)
        val receipt = relay?.submit("answer", body) ?: request("/answers", body, invite.getString("access"))
        check(receipt.getBoolean("accepted") && receipt.getString("run") == question.key.runId &&
            receipt.getString("version") == question.key.version) { "电脑回执与当前问题不符" }
    }

    companion object {
        /** 每次访问时读取当前授权，解除配对后旧客户端不能用于下一次发送。 */
        fun approved(context: Context): PairingClient? = context.getSharedPreferences("windows_pairing", Context.MODE_PRIVATE)
            .getString("endpoint", null)?.let { JSONObject(it) }?.takeIf { it.optInt("v") == 2 && MobileAccount.owner.isNotEmpty() && it.optString("owner") == MobileAccount.owner }?.let(::PairingClient)
    }

    /** 为此次申请单独创建 TLS 上下文，避免修改应用的全局证书信任设置。 */
    private fun request(path: String, body: JSONObject? = null, ticket: String? = null): JSONObject {
        val trust = object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = throw CertificateException()
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                val cert = chain.firstOrNull() ?: throw CertificateException()
                val hash = MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString("") { "%02x".format(it) }
                if (hash != pin) throw CertificateException("电脑证书与二维码不匹配")
                cert.checkValidity()
            }
        }
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(trust), null) }
        val connection = URL("https://$host:$port/mobile/v1$path").openConnection(Proxy.NO_PROXY) as HttpsURLConnection
        try {
            connection.sslSocketFactory = tls.socketFactory
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 5000
            connection.readTimeout = 5000
            connection.setRequestProperty("X-Tebb-Account", MobileAccount.proof(MobileAccount.lease(owner), "$pin:/mobile/v1$path"))
            if (ticket != null) connection.setRequestProperty("Authorization", "Bearer $ticket")
            if (body != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            when (val status = connection.responseCode) {
                200 -> Unit
                409 -> error("问题或申请已变化，请刷新后核对")
                403 -> throw PairingAuthorizationDenied()
                else -> error("电脑请求失败（$status）")
            }
            return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        } finally {
            connection.disconnect()
        }
    }
}
