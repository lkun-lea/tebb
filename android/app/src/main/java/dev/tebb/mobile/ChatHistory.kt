package dev.tebb.mobile

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** 本机聊天记录；[target] 保存发送时的问题版本，[title] 保存当时可读的任务名称。 */
internal data class ChatMessage(val id: Long, val text: String, val target: QuestionKey?, val title: String?, val fromTebb: Boolean, val windowsAccepted: Boolean)

/** 主聊天的本地数据源。历史正文存放在应用私有数据库，避免随 Activity 保存大量文本。 */
internal class ChatHistory(context: Context) : SQLiteOpenHelper(context, "chat.db", null, 3) {
    /** 首次打开数据库时创建消息表，普通聊天的任务字段为空。 */
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT NOT NULL, run TEXT, version TEXT, title TEXT, from_tebb INTEGER NOT NULL DEFAULT 0, windows_accepted INTEGER NOT NULL DEFAULT 0)")
    }

    /** 第一版仅保存用户消息，迁移后已有记录仍归属用户。 */
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) db.execSQL("ALTER TABLE messages ADD COLUMN from_tebb INTEGER NOT NULL DEFAULT 0")
        if (oldVersion < 3) db.execSQL("ALTER TABLE messages ADD COLUMN windows_accepted INTEGER NOT NULL DEFAULT 0")
    }

    /** 读取最近的记录，再按发送顺序交给聊天列表。调用方在 IO 线程执行。 */
    fun recent(): List<ChatMessage> = readableDatabase.rawQuery(
        "SELECT id, body, run, version, title, from_tebb, windows_accepted FROM messages ORDER BY id DESC LIMIT 80", null
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) {
                val key = if (cursor.isNull(2)) null else QuestionKey(cursor.getString(2), cursor.getString(3))
                add(ChatMessage(cursor.getLong(0), cursor.getString(1), key, cursor.getString(4), cursor.getInt(5) != 0, cursor.getInt(6) != 0))
            }
        }.asReversed()
    }

    /** 删除消息表中的全部记录，包括超出界面最近 80 条展示范围的历史。 */
    fun clear() {
        writableDatabase.delete("messages", null, null)
    }

    /** 在同一事务中保存提问和可选的本地回答，失败时整轮回滚。 */
    fun append(text: String, question: PendingQuestion?, answer: String?): List<ChatMessage> {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val rows = buildList {
                add(insert(db, text, question, false))
                if (answer != null) add(insert(db, answer, null, true))
            }
            db.setTransactionSuccessful()
            return rows
        } finally {
            db.endTransaction()
        }
    }

    /** 保存发送方，供历史列表还原气泡方向和桌宠停靠位置。 */
    private fun insert(db: SQLiteDatabase, text: String, question: PendingQuestion?, fromTebb: Boolean): ChatMessage {
        val values = ContentValues().apply {
            put("body", text)
            put("run", question?.key?.runId)
            put("version", question?.key?.version)
            put("title", question?.title)
            put("from_tebb", fromTebb)
            put("windows_accepted", !question?.deviceId.isNullOrEmpty())
        }
        return ChatMessage(db.insertOrThrow("messages", null, values), text, question?.key, question?.title, fromTebb, !question?.deviceId.isNullOrEmpty())
    }
}
