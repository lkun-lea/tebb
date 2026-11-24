package dev.tebb.mobile

import org.json.JSONObject
import java.net.URL
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import javax.net.ssl.HttpsURLConnection

/** 当前进程的账号会话。令牌只发往构建时配置的认证服务，电脑只会收到短期凭据的签名。 */
internal object MobileAccount {
    @Volatile var owner = ""
        private set
    private var token = ""
    private var refreshToken = ""
    private var tokenExpiry = 0L
    private var key = ByteArray(0)
    private var expiry = 0L

    /** 向已有账号发送验证码，邮箱服务不会隐式注册用户。 */
    fun sendCode(email: String) {
        post("/auth/v1/otp", JSONObject().put("email", email).put("create_user", false))
    }

    /** 验证邮箱并领取用户专属的发现凭据，两步都成功后才进入已登录状态。 */
    @Synchronized fun login(email: String, code: String) {
        val session = post("/auth/v1/verify", JSONObject().put("email", email).put("token", code).put("type", "email"))
        val identity = session.getJSONObject("user").getString("id")
        val access = session.getString("access_token")
        renew(identity, access)
        saveSession(session)
        owner = identity
    }

    /** 清除内存中的账号状态，下次访问电脑时必须重新登录。 */
    @Synchronized fun logout() {
        token = ""
        refreshToken = ""
        tokenExpiry = 0L
        owner = ""
        key = ByteArray(0)
        expiry = 0
    }

    /** 校验调用者仍属于创建连接的账号，短期密钥过期时通过认证服务重新领取。 */
    @Synchronized fun lease(expected: String): ByteArray {
        check(owner.isNotEmpty() && owner == expected) { "请登录原配对账号" }
        val now = System.currentTimeMillis() / 1000
        if (now + 30 >= tokenExpiry) {
            val session = post("/auth/v1/token?grant_type=refresh_token", JSONObject().put("refresh_token", refreshToken))
            check(session.getJSONObject("user").getString("id") == expected) { "续期账号已变化，请重新登录" }
            saveSession(session)
            expiry = 0
        }
        if (now >= expiry) renew(expected, token)
        return key
    }

    /** 为固定的 tebb HTTPS 聊天入口取得当前账号令牌，检查身份以隔离切换账号后的请求。 */
    @Synchronized fun cloudToken(expected: String): String {
        check(expected.isNotEmpty() && owner == expected) { "请先登录云端账号" }
        if (System.currentTimeMillis() / 1000 + 30 >= tokenExpiry) {
            val session = post("/auth/v1/token?grant_type=refresh_token", JSONObject().put("refresh_token", refreshToken))
            check(session.getJSONObject("user").getString("id") == expected) { "登录账号已变化" }
            saveSession(session)
        }
        return token
    }

    /** 保留服务端轮换后的会话，只在进程内使用刷新令牌。 */
    private fun saveSession(session: JSONObject) {
        token = session.getString("access_token")
        refreshToken = session.getString("refresh_token")
        tokenExpiry = System.currentTimeMillis() / 1000 + session.getLong("expires_in")
    }

    private fun renew(expected: String, access: String) {
        val value = post("/rest/v1/rpc/tebb_mobile_lan_lease", JSONObject(), access)
        val hex = value.getString("key")
        require(value.getString("user_id") == expected && hex.matches(Regex("[a-f0-9]{64}")))
        expiry = value.getLong("expires_at")
        check(expiry > System.currentTimeMillis() / 1000) { "凭据已过期，请核对手机时间" }
        key = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }

    /** 给用途和目标明确的消息签名，同一凭据可验证广播和已固定证书的 HTTPS 请求。 */
    fun proof(key: ByteArray, message: String): String = Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key, "HmacSHA256"))
        doFinal(message.toByteArray(Charsets.US_ASCII)).joinToString("") { "%02x".format(it) }
    }

    private fun post(path: String, body: JSONObject, access: String = ""): JSONObject {
        check(BuildConfig.ACCOUNT_URL.startsWith("https://") && BuildConfig.ACCOUNT_PUBLIC_KEY.isNotBlank()) {
            "此安装包尚未配置账号服务，请使用与 Windows 相同的项目配置构建"
        }
        val conn = URL(BuildConfig.ACCOUNT_URL.trimEnd('/') + path).openConnection() as HttpsURLConnection
        try {
            conn.instanceFollowRedirects = false
            conn.connectTimeout = 8000
            conn.readTimeout = 10000
            conn.requestMethod = "POST"
            conn.setRequestProperty("apikey", BuildConfig.ACCOUNT_PUBLIC_KEY)
            if (access.isNotEmpty()) conn.setRequestProperty("Authorization", "Bearer $access")
            conn.setRequestProperty("Content-Type", "application/json")
            conn.doOutput = true
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            check(conn.responseCode in 200..299) { "账号验证失败（HTTP ${conn.responseCode}），请检查验证码、登录和项目配置" }
            return JSONObject(conn.inputStream.bufferedReader().use { it.readText() }.ifBlank { "{}" })
        } finally { conn.disconnect() }
    }
}
