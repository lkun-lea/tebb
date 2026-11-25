package dev.tebb.mobile

import android.content.ContentResolver
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Surface
import androidx.compose.material.Button
import androidx.compose.material.MaterialTheme
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import com.google.zxing.BinaryBitmap
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 从系统选择器提供的图片中读取二维码，先按尺寸采样以限制大图的解码内存。 */
private fun readQr(resolver: ContentResolver, uri: Uri): String {
    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
    while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize.coerceAtLeast(1) > 1800)
        options.inSampleSize = options.inSampleSize.coerceAtLeast(1) * 2
    options.inJustDecodeBounds = false
    val image = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
        ?: error("无法读取二维码图片")
    try {
        val pixels = IntArray(image.width * image.height)
        image.getPixels(pixels, 0, image.width, 0, 0, image.width, image.height)
        val source = RGBLuminanceSource(image.width, image.height, pixels)
        return QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source))).text
    } finally {
        image.recycle()
    }
}

/**
 * 展示 [PairingViewModel] 发布的状态，并把相机或选图得到的二维码交给同一个申请入口。
 * 临时的图片读取错误属于当前界面，网络重试和申请回执由 ViewModel 管理。
 */
@Composable
internal fun PairingPanel(model: PairingViewModel, onSignOut: () -> Unit, onDecode: (Boolean) -> Unit, connectionNotice: String? = null) {
    val state by model.state.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var imageError by remember { mutableStateOf(false) }
    val camera = rememberLauncherForActivityResult(ScanContract()) { result ->
        result.contents?.let { model.scanned(it) }
    }
    val image = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) scope.launch {
            onDecode(true)
            try { model.scanned(withContext(Dispatchers.IO) { readQr(context.contentResolver, uri) }) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { imageError = true }
            finally { onDecode(false) }
        }
    }

    val nearby by model.computers.collectAsState()
    LaunchedEffect(Unit) {
        if (model.signedIn.value.isNotEmpty() && (state is PairingState.Idle || (state as? PairingState.Notice)?.canRetry == false))
            model.discover()
    }
    LaunchedEffect(nearby) {
        nearby.firstOrNull { it.has("time") && !it.has("pin") }?.let { pc ->
            val expires = (pc.getLong("time") + 45) * 1000
            kotlinx.coroutines.delay((expires - System.currentTimeMillis()).coerceAtLeast(1000))
            model.discover()
        }
    }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colors.surface,
            contentColor = MaterialTheme.colors.onSurface) {
            Column(Modifier.fillMaxWidth().padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Windows", color = MaterialTheme.colors.primary, fontSize = 16.sp)
                Text(when (val status = state) {
                    is PairingState.Paired -> status.computer
                    else -> nearby.firstOrNull()?.optString("computer") ?: "设备状态"
                }, fontSize = 26.sp)
                when (val current = state) {
                    PairingState.Connecting -> Text("正在验证电脑并提交申请…")
                    is PairingState.Pending -> Text("请在 ${current.computer} 核对并确认：${current.code}")
                    is PairingState.Paired -> {
                        Text(connectionNotice ?: "已配对")
                        TextButton(onClick = model::forgetLocal) { Text("移除本机配对记录") }
                    }
                    else -> {
                        if (current is PairingState.Notice) {
                            Text(current.message)
                            if (current.canRetry) TextButton(onClick = model::retry) { Text("重试连接") }
                        }
                        nearby.forEach { computer ->
                            if (computer.has("pin")) TextButton(onClick = { model.scanned(computer.toString()) }) { Text("配对 " + computer.getString("computer")) }
                            else Text("在线 · 通过服务器发现", color = MaterialTheme.colors.primary)
                        }
                        TextButton(onClick = { model.discover() }) { Text("刷新电脑状态") }
                    }
                }
            }
        }
        if (state !is PairingState.Paired && state !is PairingState.Pending && state != PairingState.Connecting) {
            Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colors.surface, contentColor = MaterialTheme.colors.onSurface) {
                Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("配对电脑", fontSize = 20.sp)
                    Text("首次配对时，请在电脑上打开配对码。", fontSize = 15.sp)
                    TextButton(onClick = { model.discover(local = true) }) { Text("查找局域网电脑") }
                    Button(modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp), onClick = {
                        imageError = false
                        camera.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                            .setPrompt("扫描 Windows 上的 tebb 配对码").setBeepEnabled(false))
                    }) { Text("扫码配对 Windows") }
                    TextButton(onClick = { imageError = false; image.launch("image/*") }) { Text("从图片识别配对码") }
                    if (imageError) Text("图片中未识别到配对二维码")
                }
            }
        }
        TextButton(onClick = onSignOut) { Text("退出账号") }
    }
}
