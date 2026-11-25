package dev.tebb.mobile

import java.io.Serializable

/**
 * 标识一次运行中的一轮提问。
 *
 * @property runId 原任务的运行标识。
 * @property version 本轮提问的版本，用于区分同一任务先后发出的问题。
 */
data class QuestionKey(val runId: String, val version: String) : Serializable

/** 聊天页展示的待答问题。[key] 标识问题，更新 [title] 或 [prompt] 后引用仍然有效。 */
data class PendingQuestion(val key: QuestionKey, val title: String, val prompt: String,
                           val conversation: String = "", val deviceId: String = "", val created: Long = 0, val items: String = "") : Serializable

/**
 * 主聊天输入框在一次界面更新中使用的完整状态。
 *
 * @property pending 最近一次完整快照中的待答问题。
 * @property target 当前引用的问题；为空时，草稿属于主聊天。
 * @property manuallySelected 当前引用是否由用户选定，用于在多个问题并存时保留其选择。
 * @property dismissed 仍在待答列表中、且用户已取消自动引用的问题版本。
 * @property draft 键盘输入和语音听写共用的草稿。
 * @property partial 当前轮系统返回的临时整句，可被下一条候选修订。
 * @property dictating 是否正在等待本次语音识别结果。
 */
data class ComposerState(
    val pending: List<PendingQuestion> = emptyList(),
    val target: QuestionKey? = null,
    val manuallySelected: Boolean = false,
    val dismissed: Set<QuestionKey> = emptySet(),
    val draft: String = "",
    val dictating: Boolean = false,
    val unavailable: PendingQuestion? = null,
    val partial: String = ""
) : Serializable {
    /**
     * 根据完整的待答列表重新计算引用，并清理已结束问题的取消记录。
     *
     * @param questions 当前全部待答问题。空列表表示全部问题已结束，断线时应保留上次快照。
     * @return 保留现有草稿并按本次快照更新引用的输入框状态。
     */
    fun sync(questions: List<PendingQuestion>): ComposerState {
        val current = questions.distinctBy { it.key }
        val keys = current.map { it.key }.toSet()
        val kept = target in keys && (manuallySelected || current.size == 1 || dictating || draft.isNotEmpty())
        val next = when {
            kept -> target
            // 用户已开始输入时，新出现的问题不能接管这份草稿。
            draft.isNotEmpty() || dictating -> null
            else -> current.singleOrNull()?.key?.takeUnless { it in dismissed }
        }
        return copy(pending = current, target = next, manuallySelected = kept && manuallySelected,
            dismissed = dismissed.intersect(keys))
    }

    /** 原问题已结束时撤下卡片，保留草稿的原引用，直到用户明确取消。 */
    fun verifiedSnapshot(rows: List<PendingQuestion>): ComposerState {
        val previous = pending.find { it.key == target } ?: unavailable
        if (previous != null && previous.deviceId.isNotEmpty() && (draft.isNotBlank() || dictating) &&
            rows.none { it.key == previous.key && it.deviceId == previous.deviceId }) {
            return copy(pending = rows, target = previous.key, unavailable = previous)
        }
        return copy(unavailable = null).sync(rows)
    }

    /** 输入框展示原草稿与最新候选；临时结果只替换本轮片段。 */
    val visibleDraft: String get() = appendWords(partial)

    /** 仅接收进行中的听写候选。[words] 是当前整句，而非新增的几个字。 */
    fun preview(words: String): ComposerState =
        if (dictating) copy(partial = words.trim()) else this

    /** 最终结果提交一次；服务未返回最终文本时沿用最后一次可见候选。 */
    fun finishDictation(result: String?): ComposerState {
        if (!dictating) return this
        val words = result?.trim().orEmpty().ifEmpty { partial }
        return copy(draft = appendWords(words), partial = "", dictating = false)
    }

    /** 手势被取消时丢弃临时候选，并保留按下前的完整草稿。 */
    fun cancelDictation() = copy(dictating = false, partial = "")

    /** 把一次听写附加到原草稿末尾，已有空白分隔符直接复用。 */
    private fun appendWords(words: String): String = when {
        words.isEmpty() -> draft
        draft.isEmpty() || draft.last().isWhitespace() -> draft + words
        else -> "$draft\n$words"
    }

    /** 取消当前引用并记住本轮选择，使同一问题刷新后仍保持取消。用户可通过 [select] 重新选中。 */
    fun dismiss(): ComposerState {
        val key = target ?: return this
        return copy(target = null, unavailable = null, manuallySelected = false, dismissed = dismissed + key)
    }

    /** 将 [key] 设为手动引用。如果点击时问题已经关闭，返回当前状态。 */
    fun select(key: QuestionKey): ComposerState {
        if (pending.none { it.key == key }) return this
        if (target != null && target != key && draft.isNotBlank()) return this
        return copy(target = key, unavailable = null, manuallySelected = true, dismissed = dismissed - key)
    }
}
