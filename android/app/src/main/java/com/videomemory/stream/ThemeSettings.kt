package com.videomemory.stream

import android.content.Context
import androidx.appcompat.app.AppCompatDelegate

object ThemeSettings {

    private const val PREFS_NAME = "videomemory_theme"
    private const val KEY_THEME_MODE = "theme_mode"

    fun getSavedThemeMode(context: Context): Int {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getInt(KEY_THEME_MODE, AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM)
    }

    fun saveThemeMode(context: Context, mode: Int) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(KEY_THEME_MODE, mode)
            .apply()
    }
}
