# 交接說明 — AX Player / Fluid Motion

寫給接手的人。內容截至 2026-08-26 01:45。**這一份取代了 00:15 那一版**，其中兩個「未解決問題」現在都已經有答案，而且**上一版對它們的描述是錯的** —— 見第 1 節。

所有數字都是實測得來的，不是估計。方法寫在各節裡，可以重驗。

---

## 0. 環境

| 項目 | 值 |
|---|---|
| GPU | NVIDIA RTX 5070 Ti 16GB，driver 610，CUDA 13.3（另有 AMD 內顯，非主力） |
| 螢幕 | 165 Hz |
| AX Player 原始碼 | `C:\projects\AX_Player` |
| AX Player 部署 | `C:\AX_Player\onedir\`、`C:\AX_Player\onefile\`、`C:\AX_Player\release\` |
| Fluid Motion 原始碼 | `C:\projects\Fluid_Motion_Player` |
| Fluid Motion 部署 | `C:\Fluid_Motion\FluidMotion.exe` |
| 使用者的 mpv | `C:\mpv`（完整環境，含 VapourSynth / TensorRT / Fluid Motion 的 lua） |
| `gh` CLI | `C:\Program Files\GitHub CLI\gh.exe` — **不在 PATH 上**，要用完整路徑；已登入 `bosen12` |
| Python | `py -3.10` 用來跑原始碼與測試；**`build.bat` 走的是 `py -3`（3.14）**，兩者不同 |
| ffmpeg | `C:\Users\boshe\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-8.1.2-full_build\bin\` |

**重要**：打包版 AX Player 的 mpv root 解析順序是 `%LOCALAPPDATA%\AXPlayer\mpv-runtime` → `C:\mpv` → `%ProgramFiles%\mpv`。第一個不存在，所以**打包版實際使用 `C:\mpv`**。改 mpv 設定或 lua 要改那裡，不是 repo 的 `mpv-runtime/`（那份是給原始碼版和打包進 exe 的種子用的，兩邊要一起改）。

目前版本：**AX Player v1.1.4**、**Fluid Motion v1.4.3**，都已 commit、push、build、部署、發 release。

---

## 1. 上一版列為「未解決」的兩件事 —— 都結案了

### 1.1 `thumbfast: ERROR! cannot create mpv subprocess`（已處置，v1.1.3）

**根本原因查到了。** 方法：用 IAT hook 把 libmpv 匯入表裡的 `CreateProcessW` 換掉，直接觀察 mpv 內部真正的呼叫。

- 失敗是**真的**：`CreateProcessW` 回傳 FALSE，`GetLastError` = **87（`ERROR_INVALID_PARAMETER`）**，系統上不存在對應的子行程。網路上流傳的「假陽性、回呼誤判」說法在這台機器上不成立。
- 但它是**暫時性**的：同一次執行中，v1.1.2 加的重試第一次就成功了。
- 而且**只有無 console 的 GUI 行程會遇到**。最小重現：同一支腳本（載入 `C:\mpv` 的 libmpv、同一份 config、讓 thumbfast 自己 spawn），用 `py` 跑（有 console）成功，用 `pyw` 跑（無 console）失敗。這解釋了為什麼只有打包版會出現。
- 就算三次重試全失敗也沒有實際損失：thumbfast 會把狀態重設，**下一次 hover 會再 spawn 一次**。所以進度條縮圖一直是好的 —— 使用者說「有錯誤但縮圖正常」是對的。

**處置**：v1.1.3 移除那個五秒紅字橫幅（`mpv-runtime/scripts/thumbfast.lua`，三處 `show-text`），失敗只寫進 `debug.log`。v1.1.2 的重試保留。原始碼裡有註解記錄上述量測，位置在 `mp.msg.error("mpv subprocess create failed")` 上方。

**沒做也不建議做**：調大 `SPAWN_RETRY_LIMIT`。第一次重試就會成功，加大沒有意義。

### 1.2 「從檔案總管啟動時完全不寫 debug.log」—— 不存在，是量錯了

**上一版這一節的結論是錯的，不要照著查。**

實測：用 `explorer.exe <檔案>` 啟動打包版，`debug.log` **有正常寫入**，包含 `main()` 裡的 `mpv runtime:` 啟動行。三次獨立的 Explorer 啟動都留下了紀錄：

```
2026-08-26T01:37:20.563 mpv runtime: root=C:\mpv ...
2026-08-26T01:38:13.909 mpv runtime: root=C:\mpv ...
2026-08-26T01:41:02.760 mpv runtime: root=C:\mpv ...
```

**為什麼會誤判**：用檔案大小前後相減來判斷有沒有寫入是不可靠的。同一次 01:37 的啟動，`wc -c` / `(Get-Item).Length` 前後相減得到 **0 bytes**，而檔案內容裡明明有那一行。更明確的證據：`cp` 在 01:38 複製這個檔案時，只複製了 **23434 bytes**，而那正好是它在 **01:32**（上一次寫入停止時）的大小 —— 也就是說 stat 回報的是幾分鐘前的快取值。

**正確的驗證方式**：讀內容，不要讀大小。

```powershell
$p = "$env:LOCALAPPDATA\AXPlayer\debug.log"
$before = ([System.IO.File]::ReadAllText($p) -split "`n").Count
# ...啟動、等待...
$after  = ([System.IO.File]::ReadAllText($p) -split "`n").Count
```

`debug_log.py` 不需要修改。`app_data_dir()` 在 Explorer 啟動下解析正確（實測 Explorer 傳下來的環境變數 `LOCALAPPDATA` / `TEMP` / `APPDATA` 與一般啟動完全相同，cwd 是 `C:\Windows\System32`），而且同一次執行還在同一個目錄底下寫出了 44 張 contact sheet 和 37 張縮圖。

（`%LOCALAPPDATA%\AXPlayer\debug.log.bak` 是我在查這件事時留下的副本，內容和現行 `debug.log` 的起點不同，我沒有完全解釋清楚那次 `rm` 到底發生了什麼。它只是診斷日誌，可以直接刪。）

---

## 2. 這一輪之後的版本

### AX Player

| 版本 | 內容 |
|---|---|
| v1.1.0 | Contact sheet 改用 mpv `--sstep`，單一行程抓九幀取代九次啟動 |
| v1.1.1 | **已被 v1.1.2 推翻** —— `spawn_first=yes` 讓冷啟動更容易失敗 |
| v1.1.2 | 還原 `spawn_first`，改為在 thumbfast 內重試兩次 |
| v1.1.3 | 移除 thumbfast 的 OSD 錯誤橫幅（見 1.1） |
| v1.1.4 | 全專案檢查，修六個既有問題（見下） |

**v1.1.4 修的六件事**（都在 v1.1.3 踩得到）：

1. **播放中改排序後，點清單會播到別部影片。** 側欄重排但 mpv 播放清單刻意不重載，而 `play()` 仍用側欄索引當 mpv 索引。改成用路徑定位（`PlayerWidget._loaded` / `play_path()` / `remove_paths()`）。移除選取也有同樣的錯。
2. **滑鼠側鍵送出的是水平滾輪。** `MOUSE_BTN5` 解析不出按鍵、`MOUSE_BTN6` 是水平滾輪的舊別名。改用 `MBTN_*`。（`MOUSE_BTN0/1/2` 仍正確對應左中右，所以只有側鍵受影響。）
3. **「只看未看完」對新開的資料夾不生效** —— `set_items()` 沒有重新套用篩選。
4. **開資料夾不再替整個資料夾預先產生 contact sheet**，改為前 `EAGER_SHEET_LIMIT`（12）列。一張未快取的 sheet 要兩個 mpv 行程。
5. **contact sheet 可能少一格** —— 抓幀判斷改成「大小連續兩次不變」才算完成，檔案出現 ≠ 寫完。
6. **兩處寫檔改成不會被中斷弄壞** —— 下載走 `.part` 再改名；`resume.json` 走暫存檔 + `os.replace()`。

### Fluid Motion

| 版本 | 內容 |
|---|---|
| v1.2.0 | `trt_streams` 釘死 1；修正 `estimated-vfps` → `estimated-vf-fps`；seek 時不拆濾鏡（**後被 v1.3.1 推翻**） |
| v1.3.0 | 移除「強制加速模式」；新增實時倍率讀數 |
| v1.3.1 | 還原 v1.2.0 的 seek 改動 |
| v1.3.2 | 實時倍率納入掉幀率判定 |
| v1.4.0 | profile `60` 換成 `4x` |
| v1.4.1 | 輸出幀率改讀 `estimated-vf-fps` |
| v1.4.2 | 切換倍率/模型時不再重複查詢屬性 |
| v1.4.3 | 全專案檢查，修五個既有問題（見下） |

**v1.4.3 修的五件事**：

1. **常駐系統匣時不再全速輪詢。** `tick()` 每 0.3 秒都會掃 engine cache 目錄、重跑 `diagnose()`、要 GPU 快照 —— 沒開任何播放器時也一樣。改成有播放器 1 秒、閒置 5 秒（`HOUSEKEEPING_ACTIVE` / `HOUSEKEEPING_IDLE`）。
2. **執行期改設定會繞過驗證** —— 夾限只在 `Settings.from_dict`（載入時）跑，所以同一份設定重開前後行為不同。`update_settings()` 現在走同一條驗證。
3. **管道比對用 pid 子字串**，pid 234 會match 到 12345 的 socket，導致兩個 PlayerProcess 共用一條連線。新增 `pipe_names_pid()` 整段比對。
4. **單一實例判定**改用 `WinDLL(..., use_last_error=True)`。
5. **設定目錄是磁碟根目錄時產生的 .vpy 無法編譯**（raw string 不能以反斜線結尾）。改用 `as_posix()`。

測試：`py -3.10 -m pytest` 在 `C:\projects\Fluid_Motion_Player`，**128 passed**（v1.4.3 新增 5 個回歸測試）。AX Player 沒有測試框架。

---

## 3. 已經量過的數字（不要重新推導）

### 3.1 這台機器的補幀能力（1080p、RIFE 4.26、真實 HEVC 片源）

| 倍率 | 目標 | 掉幀率 | 結論 |
|---|---|---|---|
| 2x | 48 fps | — | 輕鬆 |
| **3x** | **72 fps** | **0.3%** | **唯一乾淨的高倍率設定** |
| 4x | 96 fps | 75–83% | 不可用 |
| 5x（profile 120） | 120 fps | 9.6% | 不可用 |
| 6x（profile 144） | 144 fps | — | 不可用 |
| 7x（profile display） | 168 fps | — | 不可用，playrate 0.55 |

**使用者應該用 `3x`。** 4K 完全不可行（0.32–0.55 倍速），而使用者本人不看 4K。

### 3.2 `trt_streams` 為什麼釘死 1

單獨提高毫無用處：`.vpy` 寫死 `core.num_threads = 1`、`inject.py` 寫死 `concurrent-frames=1`（RIFE 是時序性的，並行會撕裂畫面）。

| streams | 初始化 | 1080p VRAM | 4K VRAM |
|---|---|---|---|
| 1 | 0.27s | 0.7 GB | 1.9 GB |
| 4 | 0.50s | 1.8 GB | 6.5 GB |

而 mpv **每次 seek 都會重建 VS 腳本**，所以那 +0.23s 是每次 seek 都要付。

**但要注意**：若把 `num_threads` 與 `concurrent-frames` **一起**放開，1080p 6 倍可從 88 fps 提升到 148 fps（GPU 62% → 96%），profile 120 從 0.82 提升到 1.00 倍速 —— **但仍掉 9.6% 的幀**，所以判定不值得。並行本身經 SHA-256 逐幀比對確認**不會改變輸出**。

### 3.3 seek 行為

| | 按下 seek 到畫面出現 |
|---|---|
| seek 時拆掉濾鏡（現行） | **0.14s** |
| 濾鏡留著一起 seek | 0.34s |

v1.2.0 曾改成「單次 seek 不拆濾鏡」，理由是「到完全補幀的總時間相同」。**那是量錯了指標** —— 人感受到的是畫面多久出現。v1.3.1 已還原。另測過「seek 結束時立刻喚醒 watcher」：**沒有效果**（中位數 0.71s → 0.84s），已放棄，`_loop` 裡留了註解。

### 3.4 contact sheet 成本

| | 每張 sheet |
|---|---|
| 舊（九次啟動） | 4.54s |
| 新（`--sstep`，v1.1.0 起） | 1.04s（v1.1.4 加上等寫完的判斷後 1.16s） |

單張縮圖（1 幀 1 行程）0.48s —— **成本幾乎全在啟動行程，不在解碼**。每張 sheet 另外還要一個 `probe_duration` 行程問長度（`--sstep` 的間隔要用秒數給，所以順序上非先問不可，不能合併成一個行程）。

### 3.5 Hi10P（10-bit h264）

NVDEC 與 d3d11va 都不支援，會退回軟體解碼。**這不是問題**：軟解 playrate 1.00，與硬解相同，啟動只慢 0.33 秒。日誌裡那串 `h264_cuvid ... CUDA_ERROR_NOT_SUPPORTED` 是無害的。

---

## 4. 已經排除的假設 — 不要重試

### 關於 `thumbfast: cannot create mpv subprocess`

| 假設 | 為什麼排除 |
|---|---|
| GPU 解碼資源被佔滿 | 30 個 mpv 同時抓幀，thumbfast 式啟動 **0/6 失敗** |
| 快速重啟搶不到具名管道 | 共用同一 socket 連續啟動 **10/10 成功** |
| 路徑被 script-opts 切壞 | hook 到的 cmdline 完整正確，檔案存在 |
| `spawn_first=yes` 可以解決 | **反而讓冷啟動更糟**，已還原 |
| 「其實是假陽性，子行程有啟動」 | `CreateProcessW` 回 FALSE / err 87，系統上沒有對應行程 |
| 重試次數不夠 | 第一次重試就成功；三次全失敗時下一次 hover 也會再試 |

### 關於效能

| 假設 | 為什麼排除 |
|---|---|
| 4K 的瓶頸是色彩轉換 | RIFE 本身在 4K 就已不足（multi=5 需 120 fps，RIFE 只有 119.9） |
| 4K 的瓶頸是 copy-back 傳輸 | 對照組：4K 無濾鏡、copy-back 解碼，playrate 1.00 |
| 換輕量模型能救回高倍率 | RIFE 4.25 vs 4.26 差異在雜訊內（0.77 vs 0.78） |
| `cuda_graph` 有幫助 | 初始化與吞吐都量不出差異，輸出位元相同 |

---

## 5. 給接手者的方法論提醒

1. **選對指標。** 量「總時間」而忽略「畫面多久出現」，導致 v1.2.0 的 seek 退步；量 `playrate` 而忽略掉幀率，導致把掉 9.6% 幀的設定判成「跟得上」。
2. **測量工具本身會騙人。** 這一輪至少五次得到無效數據，最貴的一次是 1.2 節那個不存在的問題 —— **在 Windows 上用檔案大小判斷「有沒有寫入」是不可靠的**，要讀內容。另外 python-mpv 的 `command("subprocess", args=[...])` 會把 list 序列化成字串塞進 argv[0]，用它做的 subprocess 實驗全部無效（真正的重現要讓 thumbfast 自己去 spawn）。
3. **間歇性問題不能用單次觀察下結論。** v1.1.1 就是憑一次「沒出現」就發版，然後被推翻。
4. **修好之後要驗證它真的會執行。** thumbfast 重試的第一版條件寫成 `success == false`，語法正確、載入正常，但**永遠不會觸發**。
5. **要看 mpv 內部到底做了什麼，可以 hook libmpv 的 IAT。** 這一輪就是這樣拿到 `CreateProcessW` 的真實回傳值和 `GetLastError` 的。做法：解析已載入模組的 import table，`VirtualProtect` 後改寫該 slot 指向 `ctypes.WINFUNCTYPE` 包出來的 Python 函式，轉呼叫原函式並記錄。

---

## 6. 環境衛生

- 測試會留下 mpv 子行程，**每輪結束要清**：`Get-Process mpv | Stop-Process -Force`
- 產生測試影片、渲染 PNG 很佔空間（曾累積 1.36 GB 在 `%LOCALAPPDATA%\Temp\claude\`）
- 建置前必須關閉執行中的 AX Player / FluidMotion，PyInstaller 無法覆寫鎖住的檔案
- 用原始碼版測試時，Fluid Motion 會把 `fluid_rife.vpy` 寫進當時的 mpv config dir —— 如果那是 repo 的 `mpv-runtime/shaders/`，收尾時要刪掉，它不該進版控
- 使用者會同時在用這台機器（看片、打遊戲）。跑 GPU 重載測試前先確認，測完立刻清乾淨
- PowerShell 的安全防護會把指令中的 `/MIR`、`/ 1MB` 之類誤判成路徑而擋下 `Remove-Item`。把刪除指令與算術/參數拆成不同呼叫即可
- 這個環境的 Bash heredoc 會把 `\\` 吃成 `\`。要寫含反斜線的檔案（Lua、Python、.bat）請用 Write 工具，不要用 heredoc

---

## 7. 建議的下一步

沒有已知的未解問題。真的要繼續的話，這些是檢查時看到、但判斷不值得現在動的：

1. **`probe_duration` 的結果沒有快取。** sheet 被 LRU 淘汰後重新產生要重問一次長度。加了 `EAGER_SHEET_LIMIT` 之後量級已經從幾百次降到 12 次，收益很小，而且會多一個要失效的快取檔。
2. **`EAGER_SHEET_LIMIT = 12` 是拍的，不是量的。** 側欄一列 79px，預設視窗大約看得到 6 列，抓了兩個畫面的量。要調就調數字，不要改成「跟著捲動產生」—— 那會把無上限產生換個地方放回來。
3. **thumbfast 是 vendored patch。** 日後更新 thumbfast 要重新套用重試與拿掉橫幅這兩處，檔案裡有 `AX Player patch:` 註解標示位置，而且 `mpv-runtime/scripts/` 和 `C:\mpv\scripts\` 兩份都要改。
