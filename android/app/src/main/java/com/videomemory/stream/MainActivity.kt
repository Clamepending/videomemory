package com.videomemory.stream

import android.Manifest
import android.content.res.Configuration
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.Image
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.util.Size
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.videomemory.stream.databinding.ActivityMainBinding
import java.io.ByteArrayOutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Collections
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicReference

@ExperimentalGetImage
class MainActivity : AppCompatActivity() {

    private data class SnapshotEndpoint(
        val host: String,
        val label: String,
        val priority: Int,
    )

    private enum class Quality(val width: Int, val height: Int) {
        LOW(640, 480),
        MEDIUM(1280, 720),
        HIGH(1920, 1080),
    }

    private lateinit var binding: ActivityMainBinding
    private var cameraProvider: ProcessCameraProvider? = null
    private var snapshotServer: SnapshotHttpServer? = null
    private val latestSnapshot = AtomicReference<ByteArray?>(null)
    private val cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var streaming = false
    private var starting = false
    private var pendingStartAfterPermission = false
    private var serverUrl: String? = null
    private var selectedQuality = Quality.MEDIUM
    private var lastSnapshotAtMs = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        requestPermissions()
        binding.btnStart.setOnClickListener { startServer() }
        binding.btnStop.setOnClickListener { stopServer() }
        binding.themeToggleButton.setOnClickListener { toggleThemeMode() }
        binding.qualityGroup.setOnCheckedChangeListener { _, checkedId ->
            selectedQuality = when (checkedId) {
                R.id.qualityLow -> Quality.LOW
                R.id.qualityHigh -> Quality.HIGH
                else -> Quality.MEDIUM
            }
        }
        binding.qualityMedium.isChecked = true
        updateThemeToggleIcon()
        renderStreamingState()
    }

    override fun onResume() {
        super.onResume()
        updateThemeToggleIcon()
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, CAMERA_PERMISSION_REQUEST)
        }
    }

    private fun hasCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun startServer() {
        if (streaming || starting) return
        if (!hasCameraPermission()) {
            pendingStartAfterPermission = true
            requestPermissions()
            return
        }
        starting = true
        latestSnapshot.set(null)
        renderStreamingState()
        startCameraAndServer()
    }

    private fun startCameraAndServer() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            try {
                cameraProvider = providerFuture.get()
                bindCameraUseCases()
                val server = snapshotServer ?: SnapshotHttpServer(SERVER_PORT) {
                    latestSnapshot.get()
                }.also {
                    snapshotServer = it
                }
                server.start()
                serverUrl = buildServerUrlDisplay()
                streaming = true
                starting = false
                renderStreamingState()
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start snapshot server", e)
                starting = false
                serverUrl = null
                snapshotServer?.stop()
                snapshotServer = null
                cameraProvider?.unbindAll()
                Toast.makeText(this, "Failed to start the snapshot server", Toast.LENGTH_SHORT).show()
                renderStreamingState()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun bindCameraUseCases() {
        val provider = cameraProvider ?: return
        val quality = selectedQuality

        val preview = Preview.Builder()
            .build()
            .also { it.setSurfaceProvider(binding.preview.surfaceProvider) }

        val analysis = ImageAnalysis.Builder()
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setTargetResolution(Size(quality.width, quality.height))
            .build()
            .also {
                it.setAnalyzer(cameraExecutor, this::analyzeFrame)
            }

        provider.unbindAll()
        provider.bindToLifecycle(
            this,
            CameraSelector.DEFAULT_BACK_CAMERA,
            preview,
            analysis,
        )
    }

    private fun analyzeFrame(imageProxy: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastSnapshotAtMs < SNAPSHOT_INTERVAL_MS) return
            val jpeg = imageProxyToJpeg(imageProxy, SNAPSHOT_JPEG_QUALITY) ?: return
            latestSnapshot.set(jpeg)
            lastSnapshotAtMs = now
        } catch (e: Exception) {
            Log.w(TAG, "Failed to encode snapshot frame", e)
        } finally {
            imageProxy.close()
        }
    }

    private fun stopServer() {
        pendingStartAfterPermission = false
        starting = false
        streaming = false
        serverUrl = null
        latestSnapshot.set(null)
        snapshotServer?.stop()
        snapshotServer = null
        cameraProvider?.unbindAll()
        renderStreamingState()
    }

    override fun onDestroy() {
        stopServer()
        cameraExecutor.shutdown()
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != CAMERA_PERMISSION_REQUEST) return
        val granted = grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }
        if (!granted) {
            pendingStartAfterPermission = false
            Toast.makeText(this, "Camera permission is required", Toast.LENGTH_SHORT).show()
            renderStreamingState()
            return
        }
        if (pendingStartAfterPermission) {
            pendingStartAfterPermission = false
            startServer()
        }
    }

    private fun renderStreamingState() {
        val active = streaming || starting
        binding.streamControlsRow.visibility = View.VISIBLE
        binding.btnStart.visibility = if (!active) View.VISIBLE else View.GONE
        binding.btnStop.visibility = if (active) View.VISIBLE else View.GONE
        binding.previewCard.visibility = if (active) View.VISIBLE else View.GONE
        binding.btnStart.isEnabled = !active
        binding.btnStop.isEnabled = active
        binding.qualityLow.isEnabled = !active
        binding.qualityMedium.isEnabled = !active
        binding.qualityHigh.isEnabled = !active
        binding.tvServerUrl.text = when {
            active && !serverUrl.isNullOrBlank() -> serverUrl
            active -> getString(R.string.server_starting)
            else -> getString(R.string.server_address_default)
        }
        if (active) {
            binding.statusText.text = getString(R.string.status_streaming)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_live_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_live)
        } else {
            binding.statusText.text = getString(R.string.status_idle)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_idle_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_idle)
        }
    }

    private fun imageProxyToJpeg(imageProxy: ImageProxy, quality: Int): ByteArray? {
        val mediaImage = imageProxy.image ?: return null
        val nv21 = yuv420888ToNv21(mediaImage)
        val yuvImage = YuvImage(nv21, ImageFormat.NV21, mediaImage.width, mediaImage.height, null)
        val output = ByteArrayOutputStream()
        val ok = yuvImage.compressToJpeg(
            Rect(0, 0, mediaImage.width, mediaImage.height),
            quality,
            output,
        )
        if (!ok) return null
        var jpegBytes = output.toByteArray()
        val rotationDegrees = imageProxy.imageInfo.rotationDegrees
        if (rotationDegrees == 0) return jpegBytes

        val bitmap = BitmapFactory.decodeByteArray(jpegBytes, 0, jpegBytes.size) ?: return jpegBytes
        val matrix = Matrix().apply { postRotate(rotationDegrees.toFloat()) }
        val rotatedBitmap = Bitmap.createBitmap(
            bitmap,
            0,
            0,
            bitmap.width,
            bitmap.height,
            matrix,
            true,
        )
        val rotatedOutput = ByteArrayOutputStream()
        rotatedBitmap.compress(Bitmap.CompressFormat.JPEG, quality, rotatedOutput)
        bitmap.recycle()
        rotatedBitmap.recycle()
        jpegBytes = rotatedOutput.toByteArray()
        return jpegBytes
    }

    private fun yuv420888ToNv21(image: Image): ByteArray {
        val ySize = image.width * image.height
        val uvSize = image.width * image.height / 4
        val nv21 = ByteArray(ySize + uvSize * 2)

        copyPlane(image.planes[0], image.width, image.height, nv21, 0, 1)
        copyPlane(image.planes[2], image.width / 2, image.height / 2, nv21, ySize, 2)
        copyPlane(image.planes[1], image.width / 2, image.height / 2, nv21, ySize + 1, 2)
        return nv21
    }

    private fun copyPlane(
        plane: Image.Plane,
        width: Int,
        height: Int,
        out: ByteArray,
        offset: Int,
        pixelStrideOut: Int,
    ) {
        val buffer = plane.buffer
        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride
        val rowData = ByteArray(rowStride)
        var outputOffset = offset

        buffer.rewind()
        for (row in 0 until height) {
            val bytesPerRow = if (pixelStride == 1 && pixelStrideOut == 1) {
                width
            } else {
                (width - 1) * pixelStride + 1
            }
            buffer.get(rowData, 0, bytesPerRow)
            var inputOffset = 0
            for (col in 0 until width) {
                out[outputOffset] = rowData[inputOffset]
                outputOffset += pixelStrideOut
                inputOffset += pixelStride
            }
            if (row < height - 1) {
                val skip = rowStride - bytesPerRow
                if (skip > 0) {
                    buffer.position(buffer.position() + skip)
                }
            }
        }
    }

    private fun buildServerUrlDisplay(): String {
        val endpoints = findSnapshotEndpoints()
        if (endpoints.isEmpty()) {
            return snapshotUrlFor("127.0.0.1")
        }
        if (endpoints.size == 1) {
            return snapshotUrlFor(endpoints.first().host)
        }
        return endpoints.joinToString("\n\n") { endpoint ->
            "${endpoint.label}\n${snapshotUrlFor(endpoint.host)}"
        }
    }

    private fun findSnapshotEndpoints(): List<SnapshotEndpoint> {
        return try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            val bestByHost = linkedMapOf<String, SnapshotEndpoint>()
            for (networkInterface in interfaces) {
                if (!networkInterface.isUp || networkInterface.isLoopback) continue
                val interfaceName = buildString {
                    append(networkInterface.name.orEmpty().lowercase())
                    append(' ')
                    append(networkInterface.displayName.orEmpty().lowercase())
                }
                val addresses = Collections.list(networkInterface.inetAddresses)
                for (address in addresses) {
                    if (
                        address !is Inet4Address ||
                        address.isLoopbackAddress ||
                        address.isLinkLocalAddress
                    ) {
                        continue
                    }
                    val hostAddress = address.hostAddress ?: continue
                    val endpoint = classifySnapshotEndpoint(interfaceName, hostAddress)
                    val existing = bestByHost[hostAddress]
                    if (existing == null || endpoint.priority < existing.priority) {
                        bestByHost[hostAddress] = endpoint
                    }
                }
            }
            bestByHost.values.sortedWith(
                compareBy<SnapshotEndpoint> { it.priority }.thenBy { it.host },
            )
        } catch (e: Exception) {
            Log.w(TAG, "Could not determine device IPs", e)
            emptyList()
        }
    }

    private fun classifySnapshotEndpoint(interfaceName: String, hostAddress: String): SnapshotEndpoint {
        val priorityAndLabel = when {
            interfaceName.contains("tailscale") || isTailscaleIpv4(hostAddress) -> {
                0 to getString(R.string.server_address_tailscale)
            }
            interfaceName.contains("wlan") || interfaceName.contains("wifi") -> {
                1 to getString(R.string.server_address_wifi)
            }
            interfaceName.contains("eth") -> {
                2 to getString(R.string.server_address_ethernet)
            }
            else -> {
                3 to getString(R.string.server_address_other)
            }
        }
        return SnapshotEndpoint(
            host = hostAddress,
            label = priorityAndLabel.second,
            priority = priorityAndLabel.first,
        )
    }

    private fun isTailscaleIpv4(hostAddress: String): Boolean {
        val octets = hostAddress.split('.')
        if (octets.size != 4) return false
        val first = octets.getOrNull(0)?.toIntOrNull() ?: return false
        val second = octets.getOrNull(1)?.toIntOrNull() ?: return false
        return first == 100 && second in 64..127
    }

    private fun snapshotUrlFor(host: String): String {
        return "http://$host:$SERVER_PORT/snapshot.jpg"
    }

    private fun toggleThemeMode() {
        val enableDarkMode = !isDarkModeActive()
        val newMode = if (enableDarkMode) {
            AppCompatDelegate.MODE_NIGHT_YES
        } else {
            AppCompatDelegate.MODE_NIGHT_NO
        }
        ThemeSettings.saveThemeMode(this, newMode)
        AppCompatDelegate.setDefaultNightMode(newMode)
    }

    private fun isDarkModeActive(): Boolean {
        val currentNightMode = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
        return currentNightMode == Configuration.UI_MODE_NIGHT_YES
    }

    private fun updateThemeToggleIcon() {
        val darkModeActive = isDarkModeActive()
        binding.themeToggleButton.setImageResource(
            if (darkModeActive) R.drawable.ic_light_mode_24 else R.drawable.ic_dark_mode_24
        )
        binding.themeToggleButton.contentDescription = getString(
            if (darkModeActive) R.string.theme_switch_to_light else R.string.theme_switch_to_dark
        )
    }

    companion object {
        private const val TAG = "VideoMemoryStream"
        private const val CAMERA_PERMISSION_REQUEST = 1001
        private const val SERVER_PORT = 8080
        private const val SNAPSHOT_INTERVAL_MS = 150L
        private const val SNAPSHOT_JPEG_QUALITY = 82
    }
}
