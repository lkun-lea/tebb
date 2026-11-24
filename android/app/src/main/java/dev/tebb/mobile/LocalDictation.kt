package dev.tebb.mobile

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import java.io.File
import java.util.concurrent.Executors
import java.util.zip.ZipInputStream

/** 将随包分发的普通话模型解压到私有目录。目录完整落盘后才发布，进程中断后可重新准备。 */
@Synchronized
internal fun openVoiceModel(context: Context): Model {
    val name = "vosk-model-small-cn-0.22"
    val target = File(context.noBackupFilesDir, name)
    if (!target.isDirectory) {
        val staging = File(context.noBackupFilesDir, "$name.tmp").apply { mkdirs() }
        ZipInputStream(context.assets.open("$name.zip")).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                if (entry.isDirectory || !entry.name.startsWith("$name/")) continue
                val file = File(staging, entry.name.removePrefix("$name/"))
                require(file.canonicalPath.startsWith(staging.canonicalPath + File.separator))
                file.parentFile?.mkdirs()
                file.outputStream().use { zip.copyTo(it) }
            }
        }
        check(staging.renameTo(target))
    }
    return Model(target.path)
}

/** 每 100 毫秒送入一块 16 kHz 单声道 PCM，将已完成的分句与仍可修订的候选拼成完整预览。 */
internal class MandarinDecoder(model: Model) : AutoCloseable {
    private val engine = Recognizer(model, 16000f)
    private var confirmed = ""
    private var last = ""

    /** 消费 [size] 个有效采样。候选发生变化时才返回新文本，以免重复刷新输入框。 */
    fun accept(samples: ShortArray, size: Int): String? {
        val complete = engine.acceptWaveForm(samples, size)
        val part = if (complete) words(engine.result, "text") else words(engine.partialResult, "partial")
        if (complete) confirmed += part
        val preview = if (complete) confirmed else confirmed + part
        if (preview == last) return null
        last = preview
        return preview
    }

    /** 收尾时读取尚未定稿的尾句，与先前已定稿的分句共同形成可编辑草稿。 */
    fun finish(): String = (confirmed + words(engine.finalResult, "text")).ifBlank { last }

    /** 中文模型输出的词间空格是分词边界，展示时只收拢汉字之间的空格。 */
    private fun words(json: String, key: String) =
        JSONObject(json).optString(key).trim().replace(hanBoundary, "")

    override fun close() = engine.close()

    private companion object {
        val hanBoundary = Regex("(?<=\\p{IsHan})\\s+(?=\\p{IsHan})")
    }
}

/** 管理一次前台按住听写。主线程负责麦克风开关，单工作线程顺序执行模型加载、解码和释放。 */
internal class LocalDictation(
    private val context: Context,
    private val preview: (String) -> Unit,
    private val finish: (String?) -> Unit,
    private val message: (String) -> Unit
) {
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var model: Model? = null
    private var preparing = false
    private var closed = false
    private var generation = 0
    private var recorder: AudioRecord? = null

    /** 提前加载模型，避免第一次按住时丢掉开头几个字。准备失败后可再次按住重试。 */
    fun prepare() {
        if (preparing || model != null || closed) return
        preparing = true
        worker.execute {
            val result = runCatching { openVoiceModel(context) }
            model = result.getOrNull()
            main.post {
                preparing = false
                if (!closed && result.isFailure) message("中文听写模型加载失败，请重试")
            }
        }
    }

    /** 已取得权限时同步开启采音。返回 true 表示本次手势确实启动了麦克风。 */
    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        val ready = model
        if (ready == null) {
            prepare()
            message("正在准备中文听写，请稍后再按住")
            return false
        }
        if (closed || recorder != null) return false
        val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val audio = try {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 32000))
        } catch (_: RuntimeException) {
            message("无法打开麦克风")
            return false
        }
        try {
            audio.startRecording()
            check(audio.recordingState == AudioRecord.RECORDSTATE_RECORDING)
        } catch (_: RuntimeException) {
            audio.release()
            message("麦克风未启动，请检查录音权限")
            return false
        }
        val id = ++generation
        recorder = audio
        worker.execute {
            val result = runCatching {
                MandarinDecoder(ready).use { decoder ->
                    val buffer = ShortArray(1600)
                    while (audio.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                        val count = audio.read(buffer, 0, buffer.size)
                        if (count <= 0) {
                            check(audio.recordingState != AudioRecord.RECORDSTATE_RECORDING)
                            break
                        }
                        decoder.accept(buffer, count)?.let { text ->
                            main.post { if (id == generation) preview(text) }
                        }
                    }
                    decoder.finish()
                }
            }
            main.post {
                if (id == generation) {
                    stop()
                    finish(result.getOrNull())
                    if (result.isFailure) message("听写中断，已保留当前文字")
                    else if (result.getOrNull().isNullOrBlank()) message("没有听到清晰语音")
                }
                audio.release()
            }
        }
        return true
    }

    /** 松手立即关闭音频采集，后台线程仅处理已经读取的尾部采样。 */
    fun stop() {
        recorder?.stop()
        recorder = null
    }

    /** 撤销本轮手势，屏蔽已经排入主线程的旧回调。 */
    fun cancel() {
        generation++
        stop()
    }

    /** 等排队中的解码结束，再释放由工作线程持有的模型。 */
    fun close() {
        closed = true
        cancel()
        worker.execute { model?.close(); model = null }
        worker.shutdown()
    }
}
