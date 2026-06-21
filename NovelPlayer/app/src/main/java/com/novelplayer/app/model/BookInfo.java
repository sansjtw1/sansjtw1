package com.novelplayer.app.model;

import java.io.Serializable;

public class BookInfo implements Serializable {
    private String bookId;
    private String title;
    private String cover;

    public BookInfo() {}

    public BookInfo(String bookId, String title, String cover) {
        this.bookId = bookId;
        this.title = title;
        this.cover = cover;
    }

    public String getBookId() { return bookId; }
    public void setBookId(String bookId) { this.bookId = bookId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getCover() { return cover; }
    public void setCover(String cover) { this.cover = cover; }
}
