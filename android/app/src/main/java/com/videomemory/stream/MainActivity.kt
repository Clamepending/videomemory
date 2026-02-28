package com.videomemory.stream

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.SurfaceHolder
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.pedro.common.ConnectChecker
import com.pedro.library.rtmp.RtmpStream
import com.videomemory.stream.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity(), ConnectChecker {

    private lateinit var binding: ActivityMainBinding
    private var rtmpStream: RtmpStream? = null
    private var streaming = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefillRtmpUrl()
        requestPermissions()
        binding.preview.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(h: SurfaceHolder) {}
            override fun surfaceChanged(h: SurfaceHolder, format: Int, width: Int, height: Int) {}
            override fun surfaceDestroyed(h: SurfaceHolder) {}
        })
        binding.btnStart.setOnClickListener { startStream() }
        binding.btnStop.setOnClickListener { stopStream() }
        renderStreamingState()
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, 0)
        }
    }

    private fun startStream() {
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter RTMP URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!url.startsWith("rtmp://", ignoreCase = true)) {
            Toast.makeText(this, "URL must start with rtmp://", Toast.LENGTH_SHORT).show()
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
        saveRtmpUrl(url)
        rtmpStream!!.startPreview(binding.preview)
        rtmpStream!!.startStream(url)
        streaming = true
        renderStreamingState()
    }

    private fun stopStream() {
        rtmpStream?.stopStream()
        rtmpStream?.stopPreview()
        streaming = false
        renderStreamingState()
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

    private fun prefillRtmpUrl() {
        if (!binding.urlInput.text.isNullOrBlank()) return
        val saved = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .getString(KEY_LAST_RTMP_URL, null)
            ?.trim()
        val initialValue = if (saved.isNullOrBlank()) getString(R.string.default_rtmp_url) else saved
        binding.urlInput.setText(initialValue)
        binding.urlInput.setSelection(initialValue.length)
    }

    private fun saveRtmpUrl(url: String) {
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .edit()
            .putString(KEY_LAST_RTMP_URL, url)
            .apply()
    }

    private fun renderStreamingState() {
        binding.btnStart.isEnabled = !streaming
        binding.btnStop.isEnabled = streaming
        binding.urlInput.isEnabled = !streaming
        if (streaming) {
            binding.statusText.text = getString(R.string.status_streaming)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_live_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_live)
        } else {
            binding.statusText.text = getString(R.string.status_idle)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_idle_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_idle)
        }
    }

    companion object {
        private const val TAG = "VideoMemoryStream"
        private const val PREFS_NAME = "videomemory_stream_prefs"
        private const val KEY_LAST_RTMP_URL = "last_rtmp_url"
    }
}
