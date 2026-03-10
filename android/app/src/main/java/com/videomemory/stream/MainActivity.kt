package com.videomemory.stream

import android.Manifest
import android.content.res.Configuration
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.view.SurfaceHolder
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatDelegate
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.widget.doAfterTextChanged
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.pedro.common.ConnectChecker
import com.pedro.library.rtmp.RtmpStream
import com.videomemory.stream.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity(), ConnectChecker {

    private lateinit var binding: ActivityMainBinding
    private var rtmpStream: RtmpStream? = null
    private var streaming = false
    private var starting = false
    private var pendingStartUrl: String? = null
    private val qrScanner: GmsBarcodeScanner by lazy {
        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .enableAutoZoom()
            .build()
        GmsBarcodeScanning.getClient(this, options)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        requestPermissions()
        binding.preview.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(h: SurfaceHolder) {
                startPendingStreamIfReady()
            }
            override fun surfaceChanged(h: SurfaceHolder, format: Int, width: Int, height: Int) {
                startPendingStreamIfReady()
            }
            override fun surfaceDestroyed(h: SurfaceHolder) {}
        })
        binding.btnStart.setOnClickListener { startStream() }
        binding.btnStop.setOnClickListener { stopStream() }
        binding.btnScanQr.setOnClickListener { scanQrCode() }
        binding.themeToggleButton.setOnClickListener { toggleThemeMode() }
        binding.urlInput.doAfterTextChanged { renderStreamingState() }
        updateThemeToggleIcon()
        renderStreamingState()
    }

    override fun onResume() {
        super.onResume()
        updateThemeToggleIcon()
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, 0)
        }
    }

    private fun startStream() {
        if (streaming || starting) return
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter RTMP URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!isSupportedRtmpUrl(url)) {
            Toast.makeText(this, "URL must start with rtmp:// or rtmps://", Toast.LENGTH_SHORT).show()
            return
        }
        if (rtmpStream == null) {
            rtmpStream = RtmpStream(this, this)
            val ok = rtmpStream!!.prepareVideo(
                width = 1280,
                height = 720,
                bitrate = 1_200_000,
                rotation = 90
            ) &&
                rtmpStream!!.prepareAudio(48000, true, 128 * 1024)
            if (!ok) {
                Toast.makeText(this, "Prepare failed", Toast.LENGTH_SHORT).show()
                rtmpStream = null
                return
            }
        }
        pendingStartUrl = url
        starting = true
        renderStreamingState()
        startPendingStreamIfReady()
    }

    private fun stopStream() {
        pendingStartUrl = null
        starting = false
        rtmpStream?.stopStream()
        rtmpStream?.stopPreview()
        streaming = false
        renderStreamingState()
    }

    private fun scanQrCode() {
        if (streaming || starting) return
        qrScanner.startScan()
            .addOnSuccessListener { barcode ->
                val raw = barcode.rawValue?.trim().orEmpty()
                val rtmpUrl = extractRtmpUrl(raw)
                if (rtmpUrl == null) {
                    Toast.makeText(this, getString(R.string.scan_qr_invalid), Toast.LENGTH_SHORT).show()
                    return@addOnSuccessListener
                }
                binding.urlInput.setText(rtmpUrl)
                binding.urlInput.setSelection(rtmpUrl.length)
                Toast.makeText(this, getString(R.string.scan_qr_success), Toast.LENGTH_SHORT).show()
            }
            .addOnFailureListener { error ->
                Log.e(TAG, "QR scan failed", error)
                Toast.makeText(this, getString(R.string.scan_qr_error), Toast.LENGTH_SHORT).show()
            }
    }

    override fun onConnectionStarted(url: String) {}
    override fun onConnectionSuccess() {
        runOnUiThread { Toast.makeText(this, "Connected", Toast.LENGTH_SHORT).show() }
    }
    override fun onConnectionFailed(reason: String) {
        Log.e(TAG, "Connection failed: $reason")
        runOnUiThread {
            Toast.makeText(this, "Failed: $reason", Toast.LENGTH_LONG).show()
            stopStream()
        }
    }
    override fun onDisconnect() {
        runOnUiThread { if (streaming) stopStream() }
    }
    override fun onAuthError() {
        runOnUiThread { Toast.makeText(this, "Auth error", Toast.LENGTH_SHORT).show() }
    }
    override fun onAuthSuccess() {}
    override fun onNewBitrate(bitrate: Long) {}

    override fun onDestroy() {
        rtmpStream?.release()
        rtmpStream = null
        super.onDestroy()
    }

    private fun extractRtmpUrl(raw: String): String? {
        if (raw.isBlank()) return null
        val embedded = Regex("""rtmps?://\S+""", RegexOption.IGNORE_CASE).find(raw)?.value ?: raw
        val cleaned = embedded.trim().trimEnd('.', ',', ';', ')', ']')
        return if (
            cleaned.startsWith("rtmp://", ignoreCase = true) ||
            cleaned.startsWith("rtmps://", ignoreCase = true)
        ) {
            cleaned
        } else {
            null
        }
    }

    private fun renderStreamingState() {
        val active = streaming || starting
        val hasUrl = !binding.urlInput.text.isNullOrBlank()
        binding.streamControlsRow.visibility = if (hasUrl || active) View.VISIBLE else View.GONE
        binding.btnStart.visibility = if (!active) View.VISIBLE else View.GONE
        binding.btnStop.visibility = if (active) View.VISIBLE else View.GONE
        binding.previewCard.visibility = if (active) View.VISIBLE else View.GONE
        binding.btnStart.isEnabled = !active && hasUrl
        binding.btnStop.isEnabled = active
        binding.urlInput.isEnabled = !active
        binding.btnScanQr.isEnabled = !active
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

    private fun isSupportedRtmpUrl(url: String): Boolean {
        return url.startsWith("rtmp://", ignoreCase = true) ||
            url.startsWith("rtmps://", ignoreCase = true)
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

    private fun startPendingStreamIfReady() {
        if (!starting || streaming) return
        if (!binding.preview.holder.surface.isValid) return
        val url = pendingStartUrl ?: return
        val stream = rtmpStream ?: return
        try {
            stream.startPreview(binding.preview)
            stream.startStream(url)
            streaming = true
            starting = false
            pendingStartUrl = null
            renderStreamingState()
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "Preview surface not ready yet", e)
            binding.preview.postDelayed({ startPendingStreamIfReady() }, 120L)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start stream", e)
            starting = false
            pendingStartUrl = null
            renderStreamingState()
            Toast.makeText(this, "Failed to start stream", Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val TAG = "VideoMemoryStream"
    }
}
