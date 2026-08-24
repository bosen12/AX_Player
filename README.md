# AX Player

一個把 [mpv](https://mpv.io/) 直接嵌入視窗的桌面播放器。介面（無邊框標題列、側邊欄片庫）用 PySide6 + QWebEngine（HTML/CSS/JS）畫，但播放本身——進度條、縮圖預覽、快捷鍵、全螢幕、字幕/音軌切換——完全交給嵌入的 mpv 自己處理，透過 [uosc](https://github.com/tomasklaen/uosc) 和 [thumbfast](https://github.com/po5/thumbfast) 這兩個 mpv 腳本畫在畫面上。這個專案刻意不重新實作 mpv 已經做得很好的東西，只補上「資料夾片庫」跟「視窗殼」這兩塊 mpv 本身沒有的功能。

## 特色

- **原生 mpv 播放體驗**：硬體解碼、進度條 hover 縮圖預覽、字幕/音軌選單、播放清單上一部/下一部，全部是 mpv/uosc/thumbfast 原本就有的功能，不是重新刻的仿製品
- **無邊框自訂視窗殼**：深色琥珀色主題，自己的標題列 + 拖曳/縮放/最大化/全螢幕
- **資料夾片庫**：開一個資料夾，自動掃描（可選遞迴含子資料夾）、產生縮圖、依檔名排序
- **拖曳開啟**：影片檔或整個資料夾直接拖進視窗
- **開啟網址播放**：吃 mpv 本身內建的串流能力（含 yt-dlp）
- **播放進度追蹤**：清單上每部影片顯示進度條 + 已看完打勾（實際的「續播」是 mpv 自己的 watch-later 機制在做，這裡只是把進度視覺化）
- **搜尋 / 多選 / 移除**：側邊欄可以打字篩選，Ctrl+點擊多選後可以「移除選取」（只從播放清單移除，不動硬碟上的檔案）
- **縮到系統匣**：關閉視窗不結束播放，系統匣選單可以真的結束程式
- **[Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) 整合**：標題列有一顆快速切換鈕，直接觸發即時補幀開關，圖示會依照 mpv 目前是否真的套用了補幀濾鏡即時反映狀態

## 系統需求

- Windows 10（1803 以上）或 Windows 11 ——需要系統內建的 `tar.exe`（bsdtar）來解壓縮 mpv 官方發行的 7z 壓縮檔
- Python 3.10（`py -3.10` 需要能在 PATH 上找到）
- 支援硬體解碼的顯示卡（非必要，但強烈建議，體驗差很多）

## 快速開始

```bash
git clone https://github.com/bosen12/AX_Player.git
cd AX_Player
run.bat
```

`run.bat` 會依序做三件事：

1. `pip install -r requirements.txt` 裝 PySide6、python-mpv
2. 如果 `mpv-runtime\` 跟 `C:\mpv` 都沒有可用的 `libmpv-2.dll`，執行 `setup_mpv.py` 自動去抓官方 mpv 建置（見下方「mpv 從哪裡來」）
3. 啟動 AX Player

第一次執行如果需要下載 mpv，會抓大約 230MB（`mpv.exe` + `libmpv-2.dll`），之後就不會再抓了。

也可以直接帶參數開啟特定檔案或資料夾：

```bash
run.bat "D:\Videos\某部動畫"
run.bat "D:\Videos\某部動畫\第01話.mkv"
```

## mpv 從哪裡來

AX Player 不會重新發明播放器核心，而是「嵌入」一份真正的 mpv。找 mpv 的順序（見 [`ax_player/paths.py`](ax_player/paths.py) 的 `default_mpv_root()`）：

1. **`mpv-runtime/`**（專案自帶的精簡版）——`mpv.exe`、`libmpv-2.dll` 由 `setup_mpv.py` 向官方 [mpv-player-windows](https://sourceforge.net/projects/mpv-player-windows/) 建置抓取；[uosc](mpv-runtime/scripts/uosc)、[thumbfast](mpv-runtime/scripts/thumbfast.lua)、字型、乾淨的 `mpv.conf`/`input.conf` 則是直接放進這個 repo（都是很小的文字/lua 檔）。這份設定**刻意不含** Anime4K 濾鏡、VapourSynth、TensorRT 這類進階設定——那些是重度客製化的東西，不該是新用戶第一次啟動就要面對的複雜度。
2. **`C:\mpv`**——如果你自己已經有一套完整的 mpv 環境（例如裝好 Anime4K 濾鏡、接了 [Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) 的補幀），AX Player 會優先偵測並直接使用，`mpv-runtime/` 的版本完全不會被碰到
3. **`%ProgramFiles%\mpv`**——標準安裝路徑的 fallback

也就是說：一般使用者 clone 下來直接 `run.bat` 就能用；重度使用者（例如專案作者自己）維持原本一整套 Anime4K/補幀設定不受影響。

想手動重新抓一次 mpv：

```bash
py -3.10 setup_mpv.py
```

## 授權注意事項（重要）

`mpv-runtime/` 抓下來的官方 mpv 建置是 **GPLv2+**。AX Player 是把 `libmpv-2.dll` **載入同一個行程**（不是另開子行程呼叫），這在 GPL 的認定下通常算「連結」——跟 LGPL 不同，GPL 沒有為動態連結的非 GPL 程式開特例。細節、以及三個可能的因應方向，寫在 [`mpv-runtime/NOTICE.md`](mpv-runtime/NOTICE.md)，在決定要把 AX Player 用什麼授權釋出之前請先看過。

`mpv-runtime/` 底下每個 vendored 元件的來源、版本、授權都列在 [`mpv-runtime/NOTICE.md`](mpv-runtime/NOTICE.md) 的表格裡。

## 快捷鍵

播放相關的快捷鍵全部是 mpv/uosc 原生的（空白鍵暫停、方向鍵快轉、`f` 全螢幕……），因為鍵盤事件是直接轉發給 mpv 處理的，不是 AX Player 自己刻的。`mpv-runtime/input.conf` 沒有內建 Anime4K 那類自訂快捷鍵——如果你想加，直接編輯那個檔案即可（或者讓 `default_mpv_root()` 指向你自己那份帶自訂快捷鍵的 mpv 設定）。

視窗殼本身：

| 按鍵 | 動作 |
|---|---|
| Esc | 全螢幕時退出全螢幕（實際上是轉發給 mpv 的 `ESC` 綁定，它本來就會 `set fullscreen no`） |

## 已知限制 / 疑難排解

- **縮圖產生變慢或系統打嗝**：縮圖是靠背景執行緒個別啟動 `mpv.exe` 子行程硬解抓幀，數量已經跟 CPU 核心數綁定並設有上限，但如果同時有其他吃 GPU 解碼資源的程式在跑（例如 Fluid Motion 正在編譯補幀引擎），還是可能撞在一起
- **`thumbfast: cannot create mpv subprocess`**：這是 thumbfast 腳本自己丟出的錯誤，代表它抓 hover 縮圖用的獨立 mpv 子行程建立失敗，通常是 GPU 解碼資源被佔滿造成的，不是 AX Player 本身的 bug
- **拖曳只能丟在側邊欄才有反應**：不會，影片區域跟側邊欄都支援拖放；如果真的沒反應，請確認拖曳的是真實檔案（不是瀏覽器分頁之類的虛擬項目）

## 專案結構

```
AX_Player/
├── run.bat                  # 一鍵啟動（含 pip install / mpv 自動抓取）
├── setup_mpv.py             # 抓官方 mpv 建置進 mpv-runtime/
├── requirements.txt
├── mpv-runtime/              # 隨附的精簡 mpv 環境（見上方「mpv 從哪裡來」）
│   ├── mpv.exe               # gitignored，由 setup_mpv.py 產生
│   ├── libmpv-2.dll          # gitignored，由 setup_mpv.py 產生
│   ├── mpv.conf / input.conf
│   ├── script-opts/          # uosc.conf、thumbfast.conf
│   ├── scripts/              # uosc/、thumbfast.lua
│   ├── fonts/
│   └── NOTICE.md             # 授權與來源清單
└── ax_player/
    ├── app.py                 # 主視窗、系統匣、資料夾掃描、播放清單
    ├── bridge.py               # QWebChannel：HTML 介面 <-> Python
    ├── player_widget.py         # 嵌入 mpv 的核心：wid 嵌入、滑鼠/鍵盤事件轉發、
    │                             #   Fluid Motion 整合、進度輪詢
    ├── paths.py                 # mpv 路徑解析、快取目錄
    ├── thumbnails.py            # 縮圖產生 + 快取淘汰
    ├── resume.py                 # 播放進度的小型 JSON 儲存
    ├── resources/                # 應用程式圖示
    └── web/                      # 介面：index.html / app.js / style.css
```

## 架構概念

AX Player 的核心設計原則：**mpv 已經把播放器這件事做得很好了，不要重做**。

- 影片畫面是一個真正嵌入（`wid=`）的原生 mpv 視窗，疊在 QWebEngineView 之下；HTML 頁面在影片區域會被「挖一個洞」（`QWidget.setMask`），滑鼠事件才能真正穿透到 mpv
- 在 Windows 上，libmpv 用 `wid` 嵌入時建立的子視窗是 `WS_DISABLED`，原生收不到滑鼠/鍵盤事件（[mpv-player/mpv#6762](https://github.com/mpv-player/mpv/issues/6762)）——`player_widget.py` 因此手動把 Qt 收到的滑鼠移動/點擊/滾輪、鍵盤按下/放開，轉發成 mpv 自己的 `mouse`/`keydown`/`keyup`/`keypress` 指令，這也是 uosc 的 hover 顯示時間軸、thumbfast 的縮圖預覽能運作的原因
- Python 與 HTML 介面之間只透過一個很薄的 `QWebChannel` bridge 溝通（`bridge.py`），只處理視窗殼跟片庫，不碰任何播放邏輯

## 授權

AX Player 本身的授權待定——見上方「授權注意事項」。`mpv-runtime/` 內個別元件的授權見 [`mpv-runtime/NOTICE.md`](mpv-runtime/NOTICE.md)。
