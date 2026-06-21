package com.novelplayer.app.util;

import android.content.Context;
import android.content.SharedPreferences;
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import com.novelplayer.app.model.PlayProgress;
import java.lang.reflect.Type;
import java.util.HashMap;
import java.util.Map;

public class ProgressManager {
    private static final String PREFS_NAME = "play_progress";
    private static final String KEY_PROGRESS = "progress_data";
    private SharedPreferences prefs;
    private Gson gson = new Gson();

    public ProgressManager(Context context) {
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public void saveProgress(String bookId, String chapterId, int position) {
        Map<String, PlayProgress> progressMap = loadAllProgress();
        PlayProgress progress = new PlayProgress();
        progress.setBookId(bookId);
        progress.setChapterId(chapterId);
        progress.setPosition(position);
        progress.setLastChapter(chapterId);
        progress.setUpdated(new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.CHINA).format(new java.util.Date()));
        progressMap.put(bookId, progress);
        String json = gson.toJson(progressMap);
        prefs.edit().putString(KEY_PROGRESS, json).apply();
    }

    public PlayProgress getProgress(String bookId) {
        Map<String, PlayProgress> progressMap = loadAllProgress();
        return progressMap.get(bookId);
    }

    public Map<String, PlayProgress> loadAllProgress() {
        String json = prefs.getString(KEY_PROGRESS, null);
        if (json == null) return new HashMap<>();
        Type type = new TypeToken<Map<String, PlayProgress>>(){}.getType();
        return gson.fromJson(json, type);
    }
}
