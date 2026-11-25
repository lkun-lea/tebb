package dev.tebb.mobile

import org.junit.Assert.*
import org.junit.Test

/** 验证 [ComposerState] 在待答快照变化、用户选择和听写回调之间如何保留草稿及其归属。 */
class ComposerStateTest {
    private val a = PendingQuestion(QuestionKey("a", "1"), "评审", "多久？")
    private val b = PendingQuestion(QuestionKey("b", "1"), "笔记", "哪份？")

    @Test fun desktopCiphertextBindsDeviceAndDirection() {
        val encrypted = "718fda3e00ff1563c251630386ec04d079ca5e1ad355".chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        fun open(stream: String) = relayCipher(javax.crypto.Cipher.DECRYPT_MODE, "demo-only", "fixture",
            ByteArray(12) { it.toByte() }, stream).doFinal(encrypted)
        assertEquals("草稿",String(open("windows"),Charsets.UTF_8))
        assertThrows(javax.crypto.AEADBadTagException::class.java) { open("phone") }
    }

    @Test fun recommendationUsesRecentSameConversationAndRespectsCorrections() {
        val current = a.copy(deviceId = "pc", conversation = "c", created = 864000)
        val related = b.copy(deviceId = "pc", conversation = "c", created = 863000)
        val other = a.copy(key = QuestionKey("other", "1"), deviceId = "pc", conversation = "other", created = 862000)
        val old = current.copy(key = QuestionKey("old", "1"), created = 1)
        val rows = listOf(other, old, related, current)
        assertEquals(listOf(current, related), suggestionSources(rows, 864000, emptySet()))
        assertEquals(listOf(other), suggestionSources(rows, 864000, setOf(suggestionId(current), suggestionId(related))))
        assertTrue(suggestionSources(rows, 864000 * 2L, emptySet()).isEmpty())
    }

    @Test fun completedQuestionWithdrawsCardWithoutReroutingItsDraft() {
        val first = a.copy(deviceId="pc")
        val next = b.copy(title=first.title,deviceId="pc")
        val input = ComposerState().sync(listOf(first)).copy(draft="45 分钟")
        val resolved = input.verifiedSnapshot(listOf(next))
        assertEquals(listOf(next),resolved.pending)
        assertEquals(first,resolved.unavailable)
        assertEquals(first.key,resolved.select(next.key).target)
        assertNull(resolved.dismiss().target)
        assertEquals(input.draft,resolved.dismiss().draft)
    }

    // 听写过程中出现第二项仍保留原引用；结果只追加一次，取消保留已有草稿。
    @Test fun speechAppendsOnceAndPreservesTask() {
        val listening = ComposerState().sync(listOf(a)).copy(draft = "已有文字", dictating = true)
            .sync(listOf(a, b))
        val finished = listening.finishDictation(" 四十五分钟 ")
        assertEquals(a.key, finished.target)
        assertEquals("已有文字\n四十五分钟", finished.draft)
        assertEquals(finished, finished.finishDictation("重复结果"))
        assertEquals("已有文字", listening.finishDictation(null).draft)
    }

    // 原问题关闭或主聊天听写时新问题到达，都不能把这段口述自动绑给另一项任务。
    @Test fun speechCannotSwitchToNewQuestion() {
        val listening = ComposerState().sync(listOf(a)).copy(dictating = true)
        assertNull(listening.sync(listOf(b)).finishDictation("四十五分钟").target)
        assertNull(ComposerState(dictating = true).sync(listOf(a)).finishDictation("聊别的").target)
    }

    // 模拟重连后重新收到同一问题，其中标题已更新，问题版本仍相同。
    @Test fun dismissSurvivesSnapshots() {
        val initial = ComposerState().sync(listOf(a))
        assertEquals(a.key, initial.target)
        val dismissed = initial.dismiss().sync(listOf(b, a)).sync(listOf(a.copy(title = "新标题")))
        assertNull(dismissed.target)
        assertEquals(a.key, dismissed.select(a.key).target)
    }

    // 一变多时撤下自动引用；手选后继续收到快照仍以用户选择为准。
    @Test fun multipleRequiresExplicitChoice() {
        val multiple = ComposerState().sync(listOf(a)).sync(listOf(a, b))
        assertNull(multiple.target)
        val selected = multiple.select(b.key).sync(listOf(b, a))
        assertEquals(b.key, selected.target)
        assertNull(selected.copy(draft = "继续").sync(listOf(a)).target)
    }

    // 同一任务的新版本属于新问题；旧版被点掉不会屏蔽它。
    @Test fun newRoundCanAutoSelect() {
        val next = a.copy(key = a.key.copy(version = "2"))
        val result = ComposerState().sync(listOf(a)).dismiss().sync(listOf(next))
        assertEquals(next.key, result.target)
        assertEquals(result, result.select(a.key))
    }

    // 普通草稿遇到待答任务保持原意，手动绑定、取消和关闭任务都保留文本。
    @Test fun existingDraftKeepsItsDestination() {
        val state = ComposerState(draft = "先聊别的").sync(listOf(a))
        assertNull(state.target)
        val cleared = state.select(a.key).dismiss().sync(listOf(a))
        assertEquals("先聊别的", cleared.draft)
        assertNull(cleared.target)
        assertTrue(cleared.sync(emptyList()).pending.isEmpty())
    }

    /** 第二个问题到达时，已经开始编辑的回答继续关联最初的问题版本。 */
    @Test fun newQuestionDoesNotDetachAnEditedReply() {
        val state = ComposerState().sync(listOf(a)).copy(draft = "45 分钟")
        val updated = state.sync(listOf(b, a))
        assertEquals(a.key, updated.target)
        assertEquals("45 分钟", updated.draft)
    }

    /** 连续临时结果可改写上一版，最终结果只追加一次；期间不改变原回复对象。 */
    @Test fun streamingRevisionsReplaceOnlyTheSpokenSuffix() {
        val input = ComposerState(draft = "会议").select(a.key).copy(dictating = true)
            .copy(pending = listOf(a), target = a.key)
        val interim = input.preview("四十").preview("四十五分钟")
        assertEquals("会议\n四十五分钟", interim.visibleDraft)
        assertEquals("会议", interim.draft)
        val final = interim.finishDictation("45 分钟")
        assertEquals(a.key, final.target)
        assertEquals("会议\n45 分钟", final.visibleDraft)
        assertEquals(final, final.preview("迟到的候选"))
        assertEquals(final, final.finishDictation("迟到的结果"))
    }

    /** 松手后若服务没有最终句，沿用最后一版；明确取消则恢复原草稿。 */
    @Test fun releaseKeepsTheLastPreviewWhileCancelRestoresOriginal() {
        val interim = ComposerState(draft = "已有文字", dictating = true).preview("补充")
        assertEquals("已有文字\n补充", interim.finishDictation(null).draft)
        assertEquals("已有文字", interim.cancelDictation().visibleDraft)
    }
}
