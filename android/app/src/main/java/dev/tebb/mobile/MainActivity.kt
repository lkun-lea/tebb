package dev.tebb.mobile

import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collectLatest
import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue

/** Android 平台入口。负责权限、本地听写及识别器生命周期，任务归属和草稿只由 ViewModel 修改。 */
class MainActivity : ComponentActivity() {
    private val chat: ChatViewModel get() = androidx.lifecycle.ViewModelProvider(this)
        .get("chat:" + MobileAccount.owner, ChatViewModel::class.java)
    private val pairing: PairingViewModel by viewModels()
    private val voice by lazy {
        LocalDictation(applicationContext, { chat.preview(it) }, { chat.finishDictation(it) }, ::message)
    }

    /** 授权窗口会打断原手势，取得授权后由下一次按住动作启动录音。 */
    private val microphone = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        message(if (granted) "请按住声波按钮说话" else "未获得麦克风权限，可继续输入文字")
    }

    /** 订阅业务状态，把界面事件交给对应的 Android 或 ViewModel 入口。 */
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.rgb(9, 9, 9)
        window.navigationBarColor = window.statusBarColor
        voice.prepare()
        // 只在前台访问配对电脑。配对变化会取消旧设备的轮询，断线时保留上次快照。
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                pairing.state.collectLatest { device ->
                    val boundChat = chat
                    if (device !is PairingState.Paired) {
                        boundChat.sharedHistory("[]")
                        boundChat.connectionNotice(null)
                        if (boundChat.state.value.composer.pending.any { it.deviceId.isNotEmpty() }) boundChat.sync(emptyList())
                        return@collectLatest
                    }
                    val client = PairingClient.approved(applicationContext)
                    if (client == null) {
                        boundChat.connectionNotice("旧配对缺少任务授权，请在两端解除并重新扫码")
                        return@collectLatest
                    }
                    var lastVerified = 0L
                    var previous: DeviceSnapshot? = null
                    client.cached(applicationContext)?.let { (time, rows, history) ->
                        boundChat.sharedHistory(history)
                        lastVerified = time
                        boundChat.sync(rows)
                        boundChat.connectionNotice("Windows 缓存 · " + android.text.format.DateFormat.format("MM-dd HH:mm", time))
                    }
                    while (isActive) {
                        val generation = boundChat.replyGeneration
                        try {
                            val snapshot = withContext(Dispatchers.IO) { client.snapshot() }
                            val rows = snapshot.rows
                            if (generation == boundChat.replyGeneration) {
                                val now = snapshot.time
                                if (previous?.rows != rows || previous?.history != snapshot.history || now - lastVerified > 60_000) {
                                    client.cache(applicationContext, snapshot)
                                    lastVerified = now
                                    previous = snapshot
                                }
                                boundChat.sharedHistory(snapshot.history)
                                boundChat.remoteSnapshot(rows, generation)
                            }
                        }
                        catch (e: CancellationException) { throw e }
                        catch (e: PairingAuthorizationDenied) {
                            boundChat.sharedHistory("[]")
                            client.clearCache(applicationContext)
                            previous = null
                            lastVerified = 0
                            boundChat.sync(emptyList())
                            boundChat.connectionNotice(e.message)
                        }
                        catch (e: Exception) {
                            if (lastVerified > 0 && System.currentTimeMillis() - lastVerified > 7L * 86400 * 1000) {
                                client.clearCache(applicationContext)
                                boundChat.sharedHistory("[]")
                                boundChat.sync(emptyList())
                                lastVerified = 0
                                previous = null
                            }
                            boundChat.connectionNotice(if (lastVerified > 0) "Windows 缓存 · " +
                            android.text.format.DateFormat.format("MM-dd HH:mm", lastVerified) else "等待电脑连接") }
                        delay(2500)
                    }
                }
            }
        }
        setContent {
            val owner by pairing.signedIn.collectAsState()
            val activeChat = androidx.compose.runtime.remember(owner) { chat }
            val state by activeChat.state.collectAsState()
            val device by pairing.state.collectAsState()
            ChatScreen(state, device, pairing, chat::select, chat::dismiss, chat::edit, chat::send,
                ::requestVoice, ::stopListening, ::cancelVoice, chat::sync, chat::readHistory, chat::clearHistory, chat::chooseCloud, chat::defer)
        }
    }

    /** 麦克风就绪后才进入采音状态，授权弹窗结束后须重新按住。 */
    private fun requestVoice() {
        if (chat.state.value.composer.dictating) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            microphone.launch(Manifest.permission.RECORD_AUDIO)
        } else if (voice.start()) chat.beginDictation()
    }

    /** 松手后结束本轮采音，等待本地解码器定稿。 */
    private fun stopListening() {
        if (!chat.state.value.listening) return
        voice.stop()
        chat.transcribing()
    }

    /** 手势取消时，丢弃本轮临时候选并恢复已有草稿。 */
    private fun cancelVoice() {
        voice.cancel()
        chat.cancelDictation()
    }

    override fun onStop() {
        if (chat.state.value.composer.dictating) cancelVoice()
        super.onStop()
    }

    override fun onDestroy() {
        voice.close()
        super.onDestroy()
    }

    /** 显示一次与本轮语音操作有关的提示。 */
    private fun message(text: String) = Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
}
