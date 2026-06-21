package com.novelplayer.app.util;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

public class MediaDetector {
    private static final String USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36";
    private static final int TIMEOUT = 15000;

    private static final Pattern AUDIO_EXT = Pattern.compile("\\.(mp3|m4a|aac|ogg|oga|wav|flac|wma|opus|amr|mid|midi|ape|alac|wv)(\\?[^#\\s]*)?$", Pattern.CASE_INSENSITIVE);
    private static final Pattern VIDEO_EXT = Pattern.compile("\\.(mp4|m4v|webm|mkv|avi|mov|flv|wmv|3gp|ts|f4v)(\\?[^#\\s]*)?$", Pattern.CASE_INSENSITIVE);
    private static final Pattern STREAM_EXT = Pattern.compile("\\.(m3u8|m3u|mpd|ism|ismc|isml)(\\?[^#\\s]*)?$", Pattern.CASE_INSENSITIVE);
    private static final Pattern IMAGE_EXT = Pattern.compile("\\.(jpg|jpeg|png|gif|bmp|ico|svg|webp|avif)(\\?[^#\\s]*)?$", Pattern.CASE_INSENSITIVE);

    public static class MediaResult {
        public String url;
        public String source;
        public String type;
        public String ext;
        public String title;

        public MediaResult(String url, String source, String type, String ext, String title) {
            this.url = url;
            this.source = source;
            this.type = type;
            this.ext = ext;
            this.title = title;
        }
    }

    public static List<MediaResult> detectFromUrl(String pageUrl, boolean analyzeJs) throws IOException {
        OkHttpClient client = new OkHttpClient.Builder()
            .followRedirects(true)
            .build();

        Request request = new Request.Builder()
            .url(pageUrl)
            .addHeader("User-Agent", USER_AGENT)
            .build();

        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) throw new IOException("HTTP " + response.code());
            String html = response.body().string();
            String baseUrl = response.request().url().toString();
            return detectMedia(html, baseUrl, null);
        }
    }

    public static List<MediaResult> detectFromHtml(String html) {
        return detectMedia(html, "", null);
    }

    private static List<MediaResult> detectMedia(String html, String baseUrl, List<String> jsContents) {
        List<MediaResult> results = new ArrayList<>();
        Set<String> seen = new HashSet<>();

        try {
            Document doc = Jsoup.parse(html);

            // HTML tags
            Elements audioTags = doc.select("audio, video");
            for (Element tag : audioTags) {
                String src = tag.attr("src");
                if (!src.isEmpty()) addResult(results, seen, src, "HTML <" + tag.tagName() + "> 标签", "", "", "");
                Elements sources = tag.select("source");
                for (Element s : sources) {
                    String sSrc = s.attr("src");
                    if (!sSrc.isEmpty()) addResult(results, seen, sSrc, "HTML <source> 标签", "", "", "");
                }
            }

            // Links
            Elements links = doc.select("a[href]");
            for (Element a : links) {
                String href = a.attr("href");
                if (isMediaUrl(href)) {
                    addResult(results, seen, href, "HTML <a> 链接", a.text().trim(), "", "");
                }
            }

            // Inline scripts
            Elements scripts = doc.select("script");
            for (Element script : scripts) {
                String content = script.html();
                if (content.length() > 5) {
                    extractFromJs(content, "内联JS", results, seen);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }

        // Regex scan
        regexScan(html, "全局正则", results, seen, baseUrl);

        return results;
    }

    private static void addResult(List<MediaResult> results, Set<String> seen, String url, String source, String title, String type, String ext) {
        if (url == null || url.length() < 10 || url.length() > 2000) return;
        url = url.trim().replaceAll("^['\"`]|['\"`]$", "");
        if (url.startsWith("//")) url = "https:" + url;
        if (url.startsWith("data:") || IMAGE_EXT.matcher(url).find()) return;
        if (!url.startsWith("http")) return;
        if (seen.contains(url)) return;
        seen.add(url);

        if (type.isEmpty()) {
            if (AUDIO_EXT.matcher(url).find()) {
                type = "audio";
                Matcher m = AUDIO_EXT.matcher(url);
                if (m.find()) ext = m.group(1);
            } else if (VIDEO_EXT.matcher(url).find()) {
                type = "video";
                Matcher m = VIDEO_EXT.matcher(url);
                if (m.find()) ext = m.group(1);
            } else if (STREAM_EXT.matcher(url).find()) {
                type = "stream";
                Matcher m = STREAM_EXT.matcher(url);
                if (m.find()) ext = m.group(1);
            } else {
                type = "unknown";
            }
        }

        results.add(new MediaResult(url, source, type, ext, title));
    }

    private static boolean isMediaUrl(String url) {
        return AUDIO_EXT.matcher(url).find() || VIDEO_EXT.matcher(url).find() || STREAM_EXT.matcher(url).find();
    }

    private static void extractFromJs(String text, String source, List<MediaResult> results, Set<String> seen) {
        Pattern[] patterns = {
            Pattern.compile("url\\s*:\\s*['\"`]([^'\"`\\s]+?)['\"`]", Pattern.CASE_INSENSITIVE),
            Pattern.compile("['\"](?:src|source|url|file|audio|mp3|stream|playUrl|audioUrl|musicUrl|mediaUrl)['\"]\\s*:\\s*['\"](https?://[^'\"`\\s]+?)['\"]", Pattern.CASE_INSENSITIVE),
        };

        for (Pattern p : patterns) {
            Matcher m = p.matcher(text);
            while (m.find()) {
                String url = m.group(1);
                if (url.startsWith("http")) {
                    addResult(results, seen, url, source + "-JS", "", "", "");
                }
            }
        }
    }

    private static void regexScan(String text, String source, List<MediaResult> results, Set<String> seen, String baseUrl) {
        Pattern[] patterns = {
            Pattern.compile("https?://[^\\s'\"`<>\\)\\]\\}]+?\\.(mp3|m4a|aac|ogg|wav|flac|opus|wma|webm|mp4|m3u8|mpd)(\\?[^\\s'\"`<>\\)\\]\\}]*)?", Pattern.CASE_INSENSITIVE),
            Pattern.compile("https?://[^\\s'\"`<>\\)\\]\\}]+?\\.m3u8[^\\s'\"`<>\\)\\]\\}]*", Pattern.CASE_INSENSITIVE),
        };

        for (Pattern p : patterns) {
            Matcher m = p.matcher(text);
            while (m.find()) {
                String url = m.group(0);
                addResult(results, seen, url, source, "", "", "");
            }
        }
    }
}
