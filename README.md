# AX Player

[English](#english) · [中文](#中文)

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Windows](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-GPLv2%2B-green)

---

## English

A Windows desktop video player that **embeds real mpv** rather than wrapping it.
The shell — a frameless title bar and a folder-based library sidebar — is native
PySide6 Qt. Everything about *playback* is mpv's own: the seek bar, hover
thumbnail previews, keybindings, fullscreen, subtitle and audio track menus, all
drawn onto the video surface by [uosc](https://github.com/tomasklaen/uosc) and
[thumbfast](https://github.com/po5/thumbfast).

That split is the whole idea. mpv already does playback better than a
reimplementation would, so this project adds only the two things mpv has no
opinion about: **a window shell, and a library for folders of episodes.**

### What it gives you that mpv alone does not

- **A folder library with thumbnails.** Point it at a directory, optionally
  recursive. Filenames sort **naturally** — episode 2 before episode 10, which
  lexicographic order gets wrong every time.
- **Watch progress at a glance.** A progress bar and a finished tick per row.
  (The actual resume is mpv's own watch-later; this visualises it.)
- **Opens on the first episode you have not finished**, rather than always the
  first file.
- **Search, multi-select, remove.** Removing takes a file out of the playlist,
  never off the disk — and there is no "delete from disk" in the row menu, by
  design.
- **Drag and drop** a file or a whole folder onto the window.
- **Play from a URL.** `setup_mpv.py` fetches `yt-dlp.exe` alongside mpv, so
  mpv's own `ytdl_hook` resolves YouTube/Twitch links.
- **Always on top**, and a one-click
  [Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) toggle whose
  icon reflects whether mpv currently has the interpolation filter loaded.

### Requirements

- Windows 10 (1803+) or 11 — the bundled `tar.exe` is used to unpack mpv's
  official 7z release
- Python 3.10, reachable as `py -3.10`
- A GPU with hardware decoding (optional, but the difference is large)

### Quick start

```bash
git clone https://github.com/bosen12/AX_Player.git
cd AX_Player
run.bat
```

`run.bat` installs dependencies, fetches mpv if neither `mpv-runtime\` nor
`C:\mpv` has a usable `libmpv-2.dll`, and launches. The first run downloads
about 79 MB if mpv is needed; after that it never does again. You can also pass
a file or folder: `run.bat "D:\Videos\Some Series"`.

### Where mpv comes from

Looked for in this order (`default_mpv_root()` in
[`ax_player/paths.py`](ax_player/paths.py)):

1. **`mpv-runtime/`** — the project's own trimmed copy. `mpv.exe` and
   `libmpv-2.dll` are fetched by `setup_mpv.py` from the official
   [mpv-player-windows](https://sourceforge.net/projects/mpv-player-windows/)
   builds and are **not** committed here; uosc, thumbfast, fonts and the config
   are.
2. **`C:\mpv`** — if you already keep a full mpv setup, it wins, and
   `mpv-runtime/` is left untouched.
3. **`%ProgramFiles%\mpv`**

### License

**GPLv2+** — see [`LICENSE`](LICENSE).

Not a casual choice: AX Player loads `libmpv-2.dll` **into its own process**
rather than shelling out to `mpv.exe`, and under the GPL that generally counts
as linking. Unlike the LGPL, the GPL carves out no exception for dynamically
linking non-GPL code. The reasoning, and the alternatives that were considered,
are in [`mpv-runtime/NOTICE.md`](mpv-runtime/NOTICE.md) — worth reading before
reusing any of this.

Note that the packaged build ships **no mpv binaries**; they are fetched at
first run into the user's own directory, so nothing here redistributes a GPL
binary.

### Contributing

Read [`CLAUDE.md`](CLAUDE.md) first — it is the orientation document, and
[`HANDOFF.md`](HANDOFF.md) is an engineering journal recording what has already
been investigated, measured and *rejected*, with the evidence. Tests:
`py -3.10 -m pytest tests -q`.

The full documentation below is in Traditional Chinese and covers keybindings,
packaging, project layout and troubleshooting in more depth.

---

## 中文

一個把 [mpv](https://mpv.io/) 直接嵌入視窗的桌面播放器。介面（無邊框標題列、側邊欄片庫）用 PySide6 原生 Qt widgets 畫，但播放本身——進度條、縮圖預覽、快捷鍵、全螢幕、字幕/音軌切換——完全交給嵌入的 mpv 自己處理，透過 [uosc](https://github.com/tomasklaen/uosc) 和 [thumbfast](https://github.com/po5/thumbfast) 這兩個 mpv 腳本畫在畫面上。這個專案刻意不重新實作 mpv 已經做得很好的東西，只補上「資料夾片庫」跟「視窗殼」這兩塊 mpv 本身沒有的功能。

## 特色

- **原生 mpv 播放體驗**：硬體解碼、進度條 hover 縮圖預覽、字幕/音軌選單、播放清單上一部/下一部，全部是 mpv/uosc/thumbfast 原本就有的功能，不是重新刻的仿製品
- **無邊框自訂視窗殼**：深色琥珀色主題，自己的標題列 + 拖曳/縮放/最大化/全螢幕
- **資料夾片庫**：開一個資料夾，自動掃描（可選遞迴含子資料夾）、產生縮圖、依檔名排序——是**自然排序**，第 2 話排在第 10 話前面，不是字典序
- **拖曳開啟**：影片檔或整個資料夾直接拖進視窗
- **開啟網址播放**：`setup_mpv.py` 會一併抓 `yt-dlp.exe`，mpv 內建的 `ytdl_hook` 用它來解析 YouTube/Twitch 等串流網站的連結
- **播放進度追蹤**：清單上每部影片顯示進度條 + 已看完打勾（實際的「續播」是 mpv 自己的 watch-later 機制在做，這裡只是把進度視覺化）
- **搜尋 / 多選 / 移除**：側邊欄可以打字篩選，Ctrl+點擊多選後可以「移除選取」（只從播放清單移除，不動硬碟上的檔案）
- **右鍵選單**：標記已看/未看、在檔案總管中顯示、複製路徑、從清單移除。這個選單裡沒有、以後也不會有「從硬碟刪除」
- **從沒看完的那一集開始**：開啟資料夾時自動跳過已看完的，停在第一部沒看完的；啟動時還原上次的片庫則**只列出清單、不自動播放**
- **視窗置頂**：標題列的圖釘鈕，一邊做事一邊看片用
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

第一次執行如果需要下載 mpv，會抓約 **79MB** 壓縮檔（`mpv.exe` 32MB + `libmpv-2.dll` 30MB + `yt-dlp.exe` 17MB，解開後約 250MB），之後就不會再抓了。

也可以直接帶參數開啟特定檔案或資料夾：

```bash
run.bat "D:\Videos\某部動畫"
run.bat "D:\Videos\某部動畫\第01話.mkv"
```

## 安裝後會發生什麼

### 只裝 AX Player

| 時機 | 動作 | 下載量 |
|---|---|---|
| 下載 | `AXPlayer.exe`（onefile） | 66 MB |
| 首次啟動 | 若機器上找不到可用的 mpv，自動抓官方建置到 `%LOCALAPPDATA%\AXPlayer\mpv-runtime\`，並把內建的 uosc / thumbfast / Anime4K / 設定檔一併播種進去 | 79 MB |
| 之後每次啟動 | 不再下載 | 0 |

裝完就能播放，Anime4K 可用（`Ctrl+1`~`3`），**補幀不可用**——那需要 Fluid Motion。

若機器上已經有 `C:\mpv` 之類的完整環境，上面的下載整個跳過，直接沿用你原本那套（見「mpv 從哪裡來」）。

### 再加上 Fluid Motion（補幀）

[Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) 是獨立的工具列程式，不是播放器。它會偵測執行中的播放器並注入 RIFE 補幀濾鏡。

| 時機 | 動作 | 下載量 |
|---|---|---|
| 下載 | `FluidMotion.exe` | 37 MB |
| 按「安裝 TensorRT 執行環境」 | VapourSynth 執行期（官方 mpv 有編進 bridge 但不附執行檔，Fluid Motion 會補上） | 21 MB |
| 同上 | TensorRT / vs-mlrt + RIFE 模型 | 約 3.5 GB |
| 首次播放每個新解析度 | 編譯 TensorRT engine（數分鐘），之後同解析度走快取 | 0 |

Fluid Motion 會**直接問播放器它正在用哪個設定目錄**再安裝進去，所以不需要手動指定路徑——AX Player 自帶的 runtime、`C:\mpv`、套件管理員裝的 mpv 都適用。

裝完之後按 `F3`（或 AX Player 標題列的 fluid 按鈕）切換補幀。補幀開啟時 Fluid Motion 會自動把解碼切成 copy-back 模式（VapourSynth 需要），關閉時還原。

## 打包成 EXE

想把 AX Player 包成 `AXPlayer.exe` 分發給別人（不需要對方裝 Python）：

```bash
build.bat
```

會裝 `pyinstaller`，用 [`AXPlayer.spec`](AXPlayer.spec) 打包，完成後複製一份到專案根目錄的 `AXPlayer\` 資料夾（裡面是 `AXPlayer.exe` 加上它的依賴檔案）。是資料夾而不是單一檔案（`--onedir` 而非 `--onefile`）——這樣每次啟動不用先把整包解壓縮到 `%TEMP%`，開啟速度快很多；分發時把整個 `AXPlayer\` 資料夾一起帶著走即可，捷徑指到裡面的 `AXPlayer.exe`。

打包進 exe 裡的東西：Python 執行環境、PySide6（QtWidgets，不含 QtWebEngine）、`ax_player/resources`，以及 `mpv-runtime/` 裡**小的**那些檔案（uosc、thumbfast、字型、`mpv.conf`/`input.conf`）。**`mpv.exe`/`libmpv-2.dll` 不會被打包進 exe**——太大、更新太頻繁。

打包好的 `AXPlayer.exe` 第一次啟動時，如果偵測不到任何可用的 mpv（`C:\mpv`、`%ProgramFiles%\mpv` 都沒有），會自動彈出一個小視窗顯示「正在準備播放引擎」，背景下載官方 mpv 建置到 `%LOCALAPPDATA%\AXPlayer\mpv-runtime\`，下載一次之後所有後續啟動都是瞬間開啟。整個過程不需要使用者自己跑 `setup_mpv.py` 或碰任何指令——這就是單一 exe 分發的意義：對方只要有網路，雙擊執行檔就好。

如果目標機器裝有一套完整的個人化 mpv 環境（`C:\mpv`），打包版一樣會優先偵測並直接使用，不會另外下載。

## mpv 從哪裡來

AX Player 不會重新發明播放器核心，而是「嵌入」一份真正的 mpv。找 mpv 的順序（見 [`ax_player/paths.py`](ax_player/paths.py) 的 `default_mpv_root()`）：

1. **`mpv-runtime/`**（專案自帶的精簡版）——`mpv.exe`、`libmpv-2.dll` 由 `setup_mpv.py` 向官方 [mpv-player-windows](https://sourceforge.net/projects/mpv-player-windows/) 建置抓取；[uosc](mpv-runtime/scripts/uosc)、[thumbfast](mpv-runtime/scripts/thumbfast.lua)、字型、乾淨的 `mpv.conf`/`input.conf` 則是直接放進這個 repo（都是很小的文字/lua 檔）。另外附帶 [Anime4K](https://github.com/bloc97/Anime4K) 著色器（約 2.4MB 純文字，**預設關閉**，見下方「快捷鍵」）。這份設定**不含** VapourSynth 與 TensorRT——補幀那一整套由 [Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) 自己安裝，它會直接問播放器目前用的是哪個設定目錄再裝進去。
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

播放相關的快捷鍵全部是 mpv/uosc 原生的（空白鍵暫停、方向鍵快轉、`f` 全螢幕……），因為鍵盤事件是直接轉發給 mpv 處理的，不是 AX Player 自己刻的。片庫相關的（`Ctrl+F`／`Ctrl+O`／`F5`／`Delete`）則是 AX Player 自己的，mpv 的 `input.conf` 沒有綁這幾顆，所以不會互相蓋掉。

### 內建綁定

| 按鍵 | 動作 |
|---|---|
| `Ctrl+1` | Anime4K **Mode A**——先修復再放大，1080p 動畫的通用選擇 |
| `Ctrl+2` | Anime4K **Mode B**——較柔和的修復，適合線條細、畫風柔的片源 |
| `Ctrl+3` | Anime4K **Mode C**——放大同時降噪，適合老片或壓縮過度的片源 |
| `Ctrl+0` | 關閉所有著色器 |
| `F1` | mpv 主控台 |
| `F3` | 切換 [Fluid Motion](https://github.com/bosen12/Fluid_Motion_Player) 補幀（需 Fluid Motion 正在執行） |
| `Ctrl+F` | 搜尋播放清單 |
| `Ctrl+O` | 開啟資料夾 |
| `F5` | 重新掃描目前的資料夾（抓新增的檔案；播放中不會中斷） |
| `Delete` | 從清單移除選取項目 |
| `Esc` | 退出全螢幕 |

Anime4K **預設關閉**，因為它是動畫放大器，套在真人影片上只會更糟。

只綁上游文件的三組標準預設。更長的手調鏈在大顯卡上效果更好，但不適合當作預設出貨——而且它們**跟 Fluid Motion 的補幀搶同一顆 GPU**。兩者一起全開在多數顯卡上會掉幀，所以診斷面板（標題列 stats 按鈕）會在兩邊同時運作時明講，否則畫面只會卡，看不出該關哪一個。

### 要改設定或快捷鍵,改哪裡

先確認你的 mpv 設定目錄是哪一個——**AX Player 啟動時會把它寫進 log**：

```
%LOCALAPPDATA%\AXPlayer\debug.log
```

找 `mpv runtime:` 開頭那行，它會列出目前使用的目錄以及該目錄具備哪些能力（VapourSynth、補幀腳本等）。接著編輯該目錄下的檔案：

| 檔案 | 用途 |
|---|---|
| `input.conf` | 快捷鍵綁定（含上面那幾組 Anime4K） |
| `mpv.conf` | mpv 本身的設定（硬解、快取、輸出……） |
| `shaders/` | 著色器檔案，可自行增減後在 `input.conf` 串成自己的鏈 |
| `script-opts/` | uosc、thumbfast 等腳本的選項 |

改完重開 AX Player 生效。

> **注意**：打包版第一次啟動會把這些檔案複製到 `%LOCALAPPDATA%\AXPlayer\mpv-runtime\`，之後就從那裡讀。改 repo 裡的 `mpv-runtime/` 不會影響已安裝的版本——請改 log 指出的那個目錄。
>
> 另外，如果你原本就有一套完整的 `C:\mpv`，AX Player 會優先用它（見「mpv 從哪裡來」），這時候要改的是 `C:\mpv` 底下的檔案。

## 已知限制 / 疑難排解

- **縮圖產生變慢或系統打嗝**：縮圖是靠背景執行緒個別啟動 `mpv.exe` 子行程硬解抓幀，數量跟 CPU 核心數綁定並設有上限。開資料夾時每部影片會產生一張 hover 用的 3×3 預覽格，過去那要啟動九次 mpv（一格一次），因為成本幾乎全在啟動行程而非解碼——單幀 0.48 秒、九幀 4.54 秒。現在改用 mpv 的 `--sstep` 在同一個行程內走完九個時間點，每張 1.04 秒，二十部影片的資料夾從約兩百個子行程降到二十個。若同時有其他吃 GPU 解碼資源的程式在跑（例如 Fluid Motion 正在編譯補幀引擎），仍可能撞在一起，只是窗口小了很多
- **`thumbfast: cannot create mpv subprocess`**：原因是 thumbfast 呼叫 mpv 的 `subprocess` 指令時帶了 `env` 參數。在 Windows 上，只要帶 `env` 而且呼叫密集，mpv 就會拒絕建立行程（`CreateProcessW` 回 FALSE、`GetLastError` 87 / `ERROR_INVALID_PARAMETER`，mpv 回報成 `status=-3` / `error_string="init"`）。滑鼠掃過側邊欄正好就是密集呼叫，所以 `debug.log` 裡的失敗永遠是**一整串**而不是零星幾筆。

  [`mpv-runtime/scripts/thumbfast.lua`](mpv-runtime/scripts/thumbfast.lua) 因此把 `env` 拿掉。不會有損失：`CreateProcessW` 的 `lpEnvironment` 傳 NULL 時子行程**直接繼承父行程的環境**，thumbfast 傳它只是為了讓 POSIX 上裸 `mpv` 能在 PATH 上被找到，而這裡 `mpv_path` 給的是絕對路徑。

  同一個 host、同一段 12 次連續請求，只差 `env`：

  | | helper 行程 | 縮圖輸出 | `create failed` |
  |---|---|---|---|
  | 不帶 `env` | 1 | 90,400 bytes | 0 |
  | 帶 `env` | 4 個都沒真的起來 | 無 | 7 |

  被拒時仍然會靜默重試兩次（間隔 0.6 秒）當保險，判斷依據是 `error_string == "init"`，所以「有啟動但立刻異常結束」這種真正的設定問題仍會立刻報出來。

  如果你用的是自己的 `C:\mpv` 而非內建 runtime，那份 `scripts/thumbfast.lua` 不含這個修改，訊息還是會出現——把 `mpv-runtime/scripts/thumbfast.lua` 複製過去即可。

  > 兩個曾經試過、但**方向就錯了**的做法，別再走一次：
  >
  > - `spawn_first=yes`（把第一次啟動提前到載入檔案時）。當時的解讀是「冷啟動比較容易被拒」，實際上冷啟動不是變因，密集度才是。
  > - 「這只發生在沒有 console 的 GUI 行程」。**不成立**：有 console 的 host 帶 `env` 一樣 8/8 失敗。當初 `py` / `pyw` 的對照差在時序，不在 console。
- **拖曳只能丟在側邊欄才有反應**：不會，影片區域跟側邊欄都支援拖放；如果真的沒反應，請確認拖曳的是真實檔案（不是瀏覽器分頁之類的虛擬項目）

## 專案結構

```
AX_Player/
├── run.bat                  # 一鍵啟動（含 pip install / mpv 自動抓取）
├── build.bat                # 打包成 AXPlayer.exe（PyInstaller）
├── AXPlayer.spec             # PyInstaller 打包設定
├── setup_mpv.py             # CLI：抓官方 mpv 建置進 mpv-runtime/
├── requirements.txt
├── packaging/
│   └── launch.py             # 打包用的進入點
├── mpv-runtime/              # 隨附的精簡 mpv 環境（見上方「mpv 從哪裡來」）
│   ├── mpv.exe               # gitignored，由 setup_mpv.py 產生
│   ├── libmpv-2.dll          # gitignored，由 setup_mpv.py 產生
│   ├── mpv.conf / input.conf
│   ├── script-opts/          # uosc.conf、thumbfast.conf
│   ├── scripts/              # uosc/、thumbfast.lua
│   ├── fonts/
│   └── NOTICE.md             # 授權與來源清單
└── ax_player/
    ├── app.py                 # 主視窗、資料夾掃描、播放清單、
    │                           #   打包版首次啟動的 mpv 下載流程
    ├── ui.py                   # 原生 Qt 介面：標題列、側邊欄片庫、清單繪製
    ├── debug_log.py             # 寫到 %LOCALAPPDATA%\AXPlayer\debug.log 的診斷紀錄
    ├── player_widget.py         # 嵌入 mpv 的核心：wid 嵌入、滑鼠/鍵盤事件轉發、
    │                             #   Fluid Motion 整合、進度輪詢
    ├── paths.py                 # mpv 路徑解析、快取目錄、打包/原始碼路徑判斷
    ├── mpv_fetch.py              # 下載官方 mpv 建置的實際邏輯（setup_mpv.py 跟
    │                             #   打包版首次啟動流程共用）
    ├── thumbnails.py            # 縮圖產生 + 快取淘汰
    ├── resume.py                 # 播放進度的小型 JSON 儲存
    └── resources/                # 應用程式圖示
```

## 架構概念

AX Player 的核心設計原則：**mpv 已經把播放器這件事做得很好了，不要重做**。

- 影片畫面是一個真正嵌入（`wid=`）的原生 mpv 視窗，跟側邊欄一樣只是 layout 裡的一個 widget——影片前面沒有任何東西擋著，滑鼠事件直接進 mpv
- 在 Windows 上，libmpv 用 `wid` 嵌入時建立的子視窗是 `WS_DISABLED`，原生收不到滑鼠/鍵盤事件（[mpv-player/mpv#6762](https://github.com/mpv-player/mpv/issues/6762)）——`player_widget.py` 因此手動把 Qt 收到的滑鼠移動/點擊/滾輪、鍵盤按下/放開，轉發成 mpv 自己的 `mouse`/`keydown`/`keyup`/`keypress` 指令，這也是 uosc 的 hover 顯示時間軸、thumbfast 的縮圖預覽能運作的原因
- 介面本身（`ui.py`）是純 Qt widgets，只處理視窗殼跟片庫，不碰任何播放邏輯。早期版本是用 QWebEngine（HTML/CSS/JS）畫的，但那等於每次啟動都要開一個完整的 Chromium 行程只為了畫一份檔案清單——而且因為影片要透過「在網頁上挖洞」（`QWidget.setMask`）才能露出來，衍生出一整類問題：全螢幕白邊、對話框畫在洞裡看不見、深色樣式套用前的白閃。改成原生 widgets 之後這些在結構上都不存在了，啟動也少掉 Chromium 那段固定成本
- 播放清單用 `QStyledItemDelegate` 繪製而不是一列一個 widget：一個資料夾可能有上千個檔案。縮圖也只在該列真的被畫出來時才去產生（等同於原本 HTML 版的 IntersectionObserver 延遲載入）

## 授權

AX Player 以 **GPLv2+** 釋出,完整條款見 [`LICENSE`](LICENSE)。

選 GPLv2+ 的原因見上方「授權注意事項」:AX Player 把 GPLv2+ 的 `libmpv-2.dll` 載入同一個行程,這在 GPL 認定下通常算連結。附帶一提,打包版**不含** mpv 二進位檔(`mpv.exe`、`libmpv-2.dll` 由 `mpv_fetch.py` 在首次啟動時抓到使用者自己的目錄),所以這裡並沒有散布 GPL 二進位檔。

`mpv-runtime/` 內個別元件的授權(Anime4K、uosc、thumbfast、字型、yt-dlp)列在 [`mpv-runtime/NOTICE.md`](mpv-runtime/NOTICE.md) 的表格。
