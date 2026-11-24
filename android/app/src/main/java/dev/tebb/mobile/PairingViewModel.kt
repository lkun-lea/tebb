package dev.tebb.mobile

import android.app.Application
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** 配对界面的一次可见状态。只有 Windows 的批准回执可以触发 [Paired]。 */
internal sealed interface PairingState {
    data object Idle : PairingState
    data object Connecting : PairingState
    data class Pending(val computer: String, val code: String) : PairingState
    data class Paired(val computer: String) : PairingState
    data class Notice(val message: String, val canRetry: Boolean = false) : PairingState
}

/**
 * 持有手机的配对申请和 Windows 的最终决定。
 *
 * [saved] 保存进行中的邀请和申请回执，页面重建后沿用同一个申请编号。
 * 已批准的设备记录写入应用私有存储。签名私钥由 [PairingClient] 从 Android Keystore 读取。
 */
internal class PairingViewModel(app: Application, private val saved: SavedStateHandle) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("windows_pairing", Context.MODE_PRIVATE)
    private val guest = MutableStateFlow(prefs.getBoolean("skip_login", false))
    val guestEntry = guest.asStateFlow()

    /** 仅保存下次启动的入口选择。访客继续使用本机能力，账号和配对仍需正常鉴权。 */
    fun rememberGuestEntry() {
        prefs.edit().putBoolean("skip_login", true).apply()
        guest.value = true
    }

    private val mutable = MutableStateFlow<PairingState>(
        PairingState.Idle
    )
    val state = mutable.asStateFlow()
    private var polling: Job? = null

    private val account = MutableStateFlow(MobileAccount.owner)
    val signedIn = account.asStateFlow()
    private val nearby = MutableStateFlow<List<JSONObject>>(emptyList())
    val computers = nearby.asStateFlow()
    private var discovery: Job? = null

    /** 在 IO 线程完成邮箱验证，成功后只恢复当前账号授权的电脑。 */
    fun authenticate(email: String, code: String) {
        if (mutable.value == PairingState.Connecting) return
        mutable.value = PairingState.Connecting
        viewModelScope.launch {
            try {
                if (code.isBlank()) {
                    withContext(Dispatchers.IO) { MobileAccount.sendCode(email.trim()) }
                    mutable.value = PairingState.Notice("请查看邮箱并填写验证码")
                } else {
                    withContext(Dispatchers.IO) { MobileAccount.login(email.trim(), code.trim()) }
                    account.value = MobileAccount.owner
                    restoreOrDiscover()
                }
            } catch (e: Exception) {
                mutable.value = PairingState.Notice(e.localizedMessage ?: "账号验证失败")
            }
        }
    }

    /** 注销后立即清空列表、待确认申请和当前连接，保留原账号的配对记录。 */
    fun signOut() {
        discovery?.cancel()
        polling?.cancel()
        clearRequest()
        MobileAccount.logout()
        account.value = ""
        nearby.value = emptyList()
        mutable.value = PairingState.Idle
    }

    private fun restoreOrDiscover() {
        if (PairingClient.approved(getApplication()) != null)
            mutable.value = PairingState.Paired(prefs.getString("computer", "") ?: "")
        else discover()
    }

    /** 登录后自动发现，刷新会取消上一轮结果；扫码或选中电脑时停止刷新。 */
    fun discover() {
        discovery?.cancel()
        nearby.value = emptyList()
        mutable.value = PairingState.Notice("正在寻找同账号电脑…")
        val owner = account.value
        discovery = viewModelScope.launch {
            try {
                nearby.value = withContext(Dispatchers.IO) { discoverComputers(owner) }
                mutable.value = if (nearby.value.isEmpty()) PairingState.Notice("未找到电脑，请检查 Wi-Fi 和电脑当前账号")
                    else PairingState.Idle
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { mutable.value = PairingState.Notice(e.localizedMessage ?: "发现失败") }
        }
    }

    init {
        if (account.value.isNotEmpty()) {
            if (saved.get<String>("invite") != null) retry() else restoreOrDiscover()
        } else clearRequest()
    }

    /** 使用相机或图片识别出的邀请开始新申请，丢弃上一张二维码的回执。 */
    fun scanned(text: String) {
        if (account.value.isEmpty()) return
        discovery?.cancel()
        nearby.value = emptyList()
        val invite = runCatching { JSONObject(text).put("owner", account.value) }.getOrNull()
        if (invite == null) {
            mutable.value = PairingState.Notice("无效的配对码")
            return
        }
        saved["invite"] = invite.toString()
        saved.remove<String>("receipt")
        retry()
    }

    /** 已取得回执时只重查电脑决定；提交阶段重试时复用设备密钥和同一张邀请。 */
    fun retry() {
        val invite = saved.get<String>("invite") ?: return
        polling?.cancel()
        mutable.value = PairingState.Connecting
        polling = viewModelScope.launch {
            try {
                val client = PairingClient(JSONObject(invite))
                val receipt = saved.get<String>("receipt")?.let { JSONObject(it) }
                    ?: withContext(Dispatchers.IO) { client.apply() }.also { saved["receipt"] = it.toString() }
                val computer = receipt.getString("computer")
                mutable.value = PairingState.Pending(computer, receipt.getString("code"))
                while (true) {
                    val decision = withContext(Dispatchers.IO) { client.status(receipt) }
                    when (decision.getString("state")) {
                        "pending" -> { delay(1000); continue }
                        "approved" -> {
                            val endpoint = JSONObject(invite).apply {
                                remove("token")
                                put("access", decision.getString("access"))
                                put("id", receipt.getString("id"))
                            }
                            prefs.edit().putString("endpoint", endpoint.toString()).putString("computer", computer).putString("id", receipt.getString("id")).apply()
                            mutable.value = PairingState.Paired(computer)
                        }
                        "rejected" -> mutable.value = PairingState.Notice("电脑已拒绝申请")
                        else -> mutable.value = PairingState.Notice("配对已过期，请重新扫码")
                    }
                    clearRequest()
                    break
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                mutable.value = PairingState.Notice("配对失败：" + (e.localizedMessage ?: "请检查同一 Wi-Fi 连接"), true)
            }
        }
    }

    /** 清除手机本地的配对记录。Windows 上的授权由电脑用户在设置页解除。 */
    fun forgetLocal() {
        prefs.edit().clear().apply()
        clearRequest()
        mutable.value = PairingState.Notice("重新配对前请在电脑上解除旧配对")
    }

    private fun clearRequest() {
        saved.remove<String>("invite")
        saved.remove<String>("receipt")
    }
}
