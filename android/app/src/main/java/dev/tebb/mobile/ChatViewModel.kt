package dev.tebb.mobile

import android.app.Application
import android.database.SQLException
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 本机 IO 期间需要独占聊天画面的操作；操作完成或失败后恢复交互。 */
internal enum class ChatWork(val label: String) { Reading("正在读取聊天"), Saving("正在保存消息"), Clearing("正在清空对话记录"),
    Queued("免费模型正在排队"), Answering("云端 tebb 正在回答") }

/** 主聊天的可观察状态。输入状态参与系统恢复；历史记录由 [ChatHistory] 重新读取。 */
internal data class ChatUiState(
    val composer: ComposerState,
    val messages: List<ChatMessage> = emptyList(),
    val work: ChatWork? = null,
    val historySnapshot: String = "[]",
    val cloud: Boolean = false,
    val listening: Boolean = false,
    val historyReadFailed: Boolean = false,
    val connectionNotice: String? = null,
    val notice: String? = null
)

/** Android 主聊天的状态所有者。界面上报事件，所有输入、引用和消息变更都从 [state] 发出。 */
internal class ChatViewModel(app: Application, private val saved: SavedStateHandle) : AndroidViewModel(app) {
    private val history = ChatHistory(app)
    private val mutable = MutableStateFlow(ChatUiState(saved["composer"] ?: ComposerState(), cloud = MobileAccount.owner.isNotEmpty() && saved.get<Boolean>("cloud") == true))
    val state = mutable.asStateFlow()

    private var verifiedQuestions = emptySet<QuestionKey>()

    /** 已确认回复的代数，用于丢弃发送前发出的迟到快照。 */
    var replyGeneration = 0L
        private set

    init {
        if (mutable.value.composer.dictating) finishDictation(null)
        readHistory()
    }

    /** 重新读取本机记录。读取失败保留已有内容，提供重试提示。 */
    fun readHistory() {
        if (mutable.value.work != null) return
        mutable.value = mutable.value.copy(work = ChatWork.Reading, notice = null)
        viewModelScope.launch {
            try {
                val rows = withContext(Dispatchers.IO) { history.recent() }
                mutable.value = mutable.value.copy(messages = rows, historyReadFailed = false)
            } catch (e: SQLException) {
                mutable.value = mutable.value.copy(historyReadFailed = true, notice = "聊天记录读取失败，请重试")
            } finally {
                mutable.value = mutable.value.copy(work = null)
            }
        }
    }

    /** 保存轻量输入状态，使屏幕重建后仍能接收听写回调并恢复草稿。 */
    private fun update(value: ComposerState) {
        saved["composer"] = value
        mutable.value = mutable.value.copy(composer = value)
    }

    /** 应用完整问题快照；问题版本、手选优先级和取消记忆由 [ComposerState.sync] 解释。 */
    fun sync(rows: List<PendingQuestion>) = update(mutable.value.composer.verifiedSnapshot(rows))

    /** 轮询不覆盖正在发送的快照；编辑中的旧引用保留，以免草稿意外改投其他任务。 */
    fun remoteSnapshot(rows: List<PendingQuestion>, generation: Long) {
        val current = mutable.value
        if (current.work == ChatWork.Saving || generation != replyGeneration) return
        val input = current.composer
        verifiedQuestions = rows.map { it.key }.toSet()
        val updated = input.verifiedSnapshot(rows)
        if (updated != input) update(updated)
        connectionNotice(null)
    }

    /** 网络故障只更新连接提示，保留最后一次成功读取的问题和正在编辑的回答。 */
    fun connectionNotice(text: String?) {
        if (text != null) verifiedQuestions = emptySet()
        mutable.value = mutable.value.copy(connectionNotice = text)
    }

    /** 当前配对账号持有的已授权原文。撤权或解除配对时以空快照替换。 */
    fun sharedHistory(snapshot: String) {
        if (mutable.value.historySnapshot != snapshot) mutable.value = mutable.value.copy(historySnapshot = snapshot)
    }

    /** 将当前草稿显式关联到用户选中的 [key]。 */
    fun select(key: QuestionKey) {
        val input = mutable.value.composer
        if (!input.dictating) update(input.select(key))
    }

    /** 移除任务引用，保留已输入文字。 */
    fun dismiss() = update(mutable.value.composer.dismiss())

    /** 使用输入框当前完整的 [text] 更新草稿。 */
    fun edit(text: String) = update(mutable.value.composer.copy(draft = text))

    /** 按下时进入采音状态，保留任务引用，在原输入框展示中间结果。 */
    fun beginDictation() {
        mutable.value = mutable.value.copy(listening = true)
        update(mutable.value.composer.copy(dictating = true))
    }

    /** 接收平台的中间候选，更新输入框而不反复提交到草稿。 */
    fun preview(words: String) = update(mutable.value.composer.preview(words))

    /** 系统或手势取消时恢复启动前的草稿。 */
    fun cancelDictation() {
        mutable.value = mutable.value.copy(listening = false)
        update(mutable.value.composer.cancelDictation())
    }

    /** 语音采集已停止，切换为全屏转写状态，继续等待系统最终结果。 */
    fun transcribing() { mutable.value = mutable.value.copy(listening = false) }

    /** 以 [words] 确认本轮听写。缺少最终文字时保留最后一次预览，恢复草稿编辑。 */
    fun finishDictation(words: String?) {
        mutable.value = mutable.value.copy(listening = false)
        update(mutable.value.composer.finishDictation(words))
    }

    /** 记录普通聊天的执行位置；关联 Windows 问题时由发送路径固定投递到原任务。 */
    fun chooseCloud(enabled: Boolean) {
        if (mutable.value.work != null || mutable.value.composer.target != null) return
        saved["cloud"] = enabled
        mutable.value = mutable.value.copy(cloud = enabled)
    }

    /** 在主线程保存请求编号，草稿和账号均相同的重试可继续读取原任务。 */
    private fun cloudRequestId(owner: String, text: String): String {
        val previous = saved.get<String>("cloudId")
        if (previous != null && saved.get<String>("cloudText") == text && saved.get<String>("cloudOwner") == owner) return previous
        val id = java.util.UUID.randomUUID().toString()
        saved["cloudId"] = id
        saved["cloudText"] = text
        saved["cloudOwner"] = owner
        return id
    }

    /** 用户主动延后一小时。取得原问题回执后撤卡，迟到的轮询不能重新展示旧卡。 */
    fun defer(question: PendingQuestion) {
        val current = mutable.value
        if (current.work != null || current.composer.draft.isNotBlank() || current.composer.dictating) return
        val client = PairingClient.approved(getApplication()) ?: return
        mutable.value = current.copy(work = ChatWork.Saving)
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { client.defer(question, System.currentTimeMillis() / 1000 + 3600) }
                replyGeneration++
                val input = mutable.value.composer
                update(input.sync(input.pending.filterNot { it.key == question.key }))
                mutable.value = mutable.value.copy(notice = "已延后一小时")
            } catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: Exception) { mutable.value = mutable.value.copy(notice = "未确认改期，请刷新核对") }
            finally { mutable.value = mutable.value.copy(work = null) }
        }
    }

    /** 核对原任务版本与编辑状态后复用聊天投递路径。已有其他草稿时保留原文并提示用户。 */
    fun replyFromJournal(key: QuestionKey, text: String) {
        val current = mutable.value
        val input = current.composer
        if (current.work != null || input.dictating || text.isBlank() || text.length > 4000) return
        if (input.pending.none { it.key == key && it.deviceId.isNotEmpty() }) {
            mutable.value = current.copy(notice = "原问题已更新，请重新查看")
            return
        }
        if (input.draft.isNotBlank() && (input.target != key || input.draft != text)) {
            mutable.value = current.copy(notice = "聊天中已有草稿，请先返回主聊处理")
            return
        }
        update(input.select(key).copy(draft = text))
        send()
    }

    /** 冻结本次正文与任务版本，写入成功后清空草稿；失败时保留草稿及其目标。 */
    fun send() {
        val current = mutable.value
        val input = current.composer
        val text = input.draft.trim()
        if (text.isEmpty() || current.work != null || input.dictating) return
        val question = input.pending.find { it.key == input.target } ?: input.unavailable
        if (question != null && question.deviceId.isNotEmpty() && question.key !in verifiedQuestions &&
            (current.connectionNotice != null || PairingClient.approved(getApplication())?.usesRelay != true)) {
            mutable.value = current.copy(notice = "草稿已保留，请等原问题重新确认后发送")
            return
        }
        val cloud = current.cloud && input.target == null
        val owner = MobileAccount.owner
        if (cloud && (owner.isBlank() || text.length > 4000)) {
            mutable.value = current.copy(notice = if (owner.isBlank()) "请先登录云端账号" else "消息最多 4000 字")
            return
        }
        val requestId = if (cloud) cloudRequestId(owner, text) else ""
        mutable.value = current.copy(work = ChatWork.Saving, notice = null)
        viewModelScope.launch {
            try {
                val remote = question?.takeIf { it.deviceId.isNotEmpty() }
                val message = withContext(Dispatchers.IO) {
                    if (remote != null) {
                        require(text.length <= 4000) { "回答最多 4000 字" }
                        val client = PairingClient.approved(getApplication()) ?: error("请重新配对 Windows")
                        client.answer(remote, text)
                    }
                    val reply = if (cloud) {
                        CloudChatClient.answer(owner, requestId, text) { progress ->
                            withContext(Dispatchers.Main) { mutable.value = mutable.value.copy(work = progress) }
                        }.also { check(MobileAccount.owner == owner) { "登录账号已变化" } }
                    } else if (question == null) starterAnswer(text, input.pending) else null
                    history.append(text, question, reply)
                }
                mutable.value = mutable.value.copy(messages = (mutable.value.messages + message).takeLast(80))
                if (cloud) saved.remove<String>("cloudId")
                val latest = mutable.value.composer
                val remaining = latest.pending.filterNot { it.key == question?.key && (remote != null || BuildConfig.DEBUG && it in demoQuestions) }
                update(latest.copy(draft = "").sync(remaining))
                if (remote != null) {
                    replyGeneration++
                    mutable.value = mutable.value.copy(notice = "Windows 已接收回答，原任务已恢复调度")
                }
            } catch (e: SQLException) {
                mutable.value = mutable.value.copy(notice = "本机保存失败，草稿已保留，可重试")
            } catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: Exception) {
                if (e is CloudTaskEnded) saved.remove<String>("cloudId")
                mutable.value = mutable.value.copy(notice = (if (cloud) "云端任务未完成，草稿已保留：" else "未取得 Windows 回执，草稿已保留：") + (e.localizedMessage ?: "连接失败"))
            } finally {
                mutable.value = mutable.value.copy(work = null)
            }
        }
    }

    /** 用户确认后清空本机历史。删除成功才刷新消息列表，草稿和任务引用继续由输入状态持有。 */
    fun clearHistory() {
        val current = mutable.value
        if (current.work != null || current.composer.dictating || current.messages.isEmpty()) return
        mutable.value = current.copy(work = ChatWork.Clearing, notice = null)
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { history.clear() }
                mutable.value = mutable.value.copy(messages = emptyList(), historyReadFailed = false)
            } catch (e: SQLException) {
                mutable.value = mutable.value.copy(notice = "清空失败，请重试")
            } finally {
                mutable.value = mutable.value.copy(work = null)
            }
        }
    }

    /** 页面离开且状态所有者销毁后释放数据库连接。 */
    override fun onCleared() { history.close() }
}

/** 调试包可从待答面板载入的示例快照；示例与真实 Windows 运行编号相互独立。 */
internal val demoQuestions = listOf(
    PendingQuestion(QuestionKey("demo-review", "1"), "周三评审", "这场评审安排多久？"),
    PendingQuestion(QuestionKey("demo-notes", "1"), "整理笔记", "使用哪份笔记作为来源？")
)




/** 首屏建议仅使用手机时间与当前任务快照，离线也能得到真实回答。 */
internal val chatStarters = listOf("今天星期几？", "现在几点了？", "有什么待答任务？")

private fun starterAnswer(text: String, pending: List<PendingQuestion>): String? {
    fun now(pattern: String) = java.text.SimpleDateFormat(pattern, java.util.Locale.SIMPLIFIED_CHINESE).format(java.util.Date())
    return when (text) {
        chatStarters[0] -> "今天是${now("M月d日，EEEE")}。"
        chatStarters[1] -> "现在是${now("HH:mm")}。"
        chatStarters[2] -> if (pending.isEmpty()) "手机上目前没有待答任务。" else
            "有 ${pending.size} 个问题待确认：" + pending.joinToString("、") { it.title }
        else -> null
    }
}
