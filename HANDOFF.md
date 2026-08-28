# 交接說明 — AX Player / Fluid Motion

寫給接手的人。內容截至 2026-08-28。

**第 1 節被改寫過兩次，兩次都是因為前一版寫錯了。** 01:45 那一版說 thumbfast 的 spawn 失敗是「暫時性、只發生在無 console 的行程、縮圖其實正常」—— 三句都不成立。根因（`subprocess` 的 `env` 參數）在 v1.1.5 才找到，見 §1.1。

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

目前版本：**AX Player v1.1.7**、**Fluid Motion v1.4.5**，都已 commit、push、build、部署、發 release。

---

## 1. 兩個長期問題 —— 都結案了

### 1.1 `thumbfast: ERROR! cannot create mpv subprocess`

**⚠️ 這一節在 08-26 01:45 那一版是錯的。真正的根因見下面的「根因與修法」。**

當時查到而且**正確**的部分：用 IAT hook 把 libmpv 匯入表裡的 `CreateProcessW` 換掉之後，觀察到失敗是真的 —— `CreateProcessW` 回傳 FALSE，`GetLastError` = **87（`ERROR_INVALID_PARAMETER`）**，系統上不存在對應的子行程。「假陽性、回呼誤判」的說法在這台機器上不成立。

建立在那個觀察之上、而且**都是錯的**推論：

| 當時的結論 | 實際 |
|---|---|
| 「它是暫時性的，第一次重試就會成功」 | 不是。日誌裡 159 次失敗只換到 24 次重試，而且 A/B 對照下帶 `env` 是 100% 失敗 |
| 「只有無 console 的 GUI 行程會遇到」 | 不是。有 console 的 host 一樣 8/8 失敗。`py` / `pyw` 的差別在時序，不在 console |
| 「縮圖一直是好的」 | 不是。130 筆 `overlay-add: could not open or map ...thumbfast.out<pid>.bgra` —— helper 沒起來，圖檔不存在 |
| 「調大 `SPAWN_RETRY_LIMIT` 沒有意義」 | 理由錯了（不是「第一次重試就會成功」），但結論碰巧對：真正的修法不在重試次數 |

**當時為什麼會被騙過去**：v1.1.2 的驗證方法是「把 `mpv_path` 指向一個啟動不了的檔案，看到兩次靜默重試然後一次錯誤」。那個方法**無法區分**「預算正確地為一個真的壞路徑用盡」和「預算對暫時性失敗永遠回不來」—— 兩者看起來一模一樣。

**處置**：v1.1.3 移除了那個五秒紅字橫幅（`mpv-runtime/scripts/thumbfast.lua`，三處 `show-text`），失敗只寫進 `debug.log`。那件事本身仍然是對的 —— 只是它治的是症狀。

#### 根因與修法（v1.1.5）

**是 `env` 參數。** thumbfast 的 `subprocess()` 包裝一直傳 `env = "PATH="..os.getenv("PATH")`。在 Windows 上，只要帶 `env` 而且呼叫密集，mpv 的 subprocess 實作就會拒絕建立行程。

量法：對 `C:\mpv` 的 libmpv host 用 raw JSON IPC 直接發 `subprocess` 指令（避開 §5 講的 python-mpv 序列化陷阱），同一條指令重複 8 次 ——

```
--- 背靠背，中間不停 ---
8x 不帶 env                            ........      (. = 成功, X = 拒絕)
8x 帶 env                              XXXXXXXX
8x 不帶 env（在 env 那輪之後再跑一次）   ........
--- 中間隔 0.5 秒 ---
8x 帶 env，隔 0.5 秒                    ........
8x 不帶 env，隔 0.5 秒                  ........
```

密集度是另一半變因，這也解釋了為什麼日誌裡的失敗永遠是**一整串**（02:11:32.309 / .327 / .651 / .657 / .663 / 33.739 / 33.745 / 33.850）—— 滑鼠掃過側邊欄就是 burst。

**修法**：`mpv-runtime/scripts/thumbfast.lua` 的 `subprocess()` 拿掉 `env`。`CreateProcessW` 的 `lpEnvironment` 傳 NULL 時子行程直接繼承父行程的環境，PATH 本來就在；thumbfast 傳它只是為了讓 POSIX 上裸 `mpv` 能在 PATH 上解析，而這裡 `mpv_path` 是絕對路徑。

**端到端驗證**（AX Player 形狀的 host：嵌入 libmpv、無 console、`config_dir=C:\mpv`、真實檔案播放中、連發 12 次 thumbfast 的 `thumb` script-message）：

| | helper `mpv.exe` | 縮圖輸出 | `create failed` |
|---|---|---|---|
| 不帶 `env` | 1 | `thumbfast.out41868.bgra` **90,400 bytes** | **0** |
| 帶 `env`（把 `env` 加回去的對照組） | 4 個都沒真的起來 | 無 | 7 |

**順帶修掉的獨立缺陷**：重試預算原本是 module-level 的 `spawn_retries`，而歸零只寫在「**已 spawn 的** helper 正常退出」那個分支裡。thumbfast 的 helper 是長駐行程，所以在「從頭到尾沒 spawn 成功過」的 session 裡預算永遠回不來 —— 前兩次失敗之後每次 hover 都直接報錯不重試。現在改成把 `retries` 當參數傳給 `spawn()`，每次新的 spawn 都有完整預算。

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
| v1.1.5 | **thumbfast 根因** —— `subprocess` 的 `env` 參數（見 §1.1）；另修三個既有問題（見下） |
| v1.1.6 | 快取寫入不會被中斷弄壞；清掉舊版留下的垃圾（見下） |
| v1.1.7 | code-review 找到的三個（見 §7）；另兩個量完撤回 |

**v1.1.6 修的四件事**：

1. **contact sheet 改成先寫暫存檔再改名。** 直接寫目的檔會留下一個「半張 JPEG」的窗口，而它通過 `is_file() and st_size > 0` 檢查，之後**每次 hover 都是那張壞圖** —— 沒有東西會重訪已存在的 sheet。同檔案的 thumbnail 早就是這樣寫的，這是兩個專案裡最後一個沒改的寫入點。
2. **`debug.log` 1 MB 輪替，保留一代。** 它只會長：mpv 的 warn/error 全進來，一個吵的腳本一個 session 就能加幾千行（thumbfast 那件事貢獻了 1275 行）。不設上限等於自我否定 —— 它是 `console=False` 建置**唯一**的診斷管道，沒人會為了找一行去讀 50 MB。
3. **清掉被遺棄的暫存目錄。** 抓幀器自己會在 `finally` 清，但行程被砍就清不掉，而 `prune_cache` 只看檔案 —— 那些東西對大小上限和淘汰**都是隱形的**。實測快取裡躺著 8 個、48 個孤兒幀。只刪超過一小時的（對照抓幀本身的 30 秒 `GRAB_TIMEOUT`）。
4. **刪掉舊 grid 尺寸的 sheet。** 檔名帶格數，而查詢只問當前格數，所以 4×3 時代留下的 `_12.jpg` 永遠讀不到，只是佔著大小上限等 LRU 掃到。實測還有 19 個。

**v1.1.5 修的四件事**：

1. **`thumbfast: cannot create mpv subprocess` 的真正原因是 `env`** —— 見 §1.1。同時把重試預算從 module-level 計數器改成 `spawn()` 的參數，原本的歸零只寫在「已 spawn 的 helper 正常退出」分支，helper 從沒起來過的 session 預算永遠回不來。
2. **遞迴模式下點子目錄的影片，整個媒體庫被換成那個子目錄。** `play()` 用「是不是開啟資料夾的直接子檔案」判斷，開了「含子資料夾」之後每個子目錄裡的檔案都不符合，於是每次點擊都走 `open_folder(video.parent)` 重新 re-root（`last_folder` 也跟著改）。改判「在不在目前的 `_playlist` 裡」。
3. **contact sheet 被 LRU 淘汰後永遠不再產生。** `_requested_sheets` 只加不刪，快取檔被 `prune_cache` 刪掉之後，快取查詢落空、in-flight 檢查又提早 return，popup 永遠停在「正在產生預覽…」。改成完成時 discard。（`_requested_thumbs` 刻意不比照辦理：縮圖是 delegate 的 paint 觸發的，discard 會讓壞檔每次重繪都重排一次；sheet 只由 hover 觸發，前面還有 350ms 的 intent 延遲。）
4. **抓幀逾時仍可能把少格的 sheet 永久快取。** v1.1.4 只堵了「檔案還沒寫完就被讀」這一條，`_grab_evenly_spaced` 撞到 `GRAB_TIMEOUT` 時會回傳已完成的部分。現在只要短少就改走逐幀 fallback（順便修掉 fallback 缺格時時間戳會錯位的問題）。

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
| v1.4.4 | 三個既有問題（見下） |
| v1.4.5 | 多播放器身分混淆（四件），外加兩個小的（見下） |

**v1.4.5 修的六件事**（前四件只有同時開兩個播放器才踩得到，這也是它們活這麼久的原因；v1.4.3 修的 pid 子字串誤配是同一家族的第一個）：

1. **seek 的 hold-off 改成逐播放器。** 原本是一個共用檔：每個 mpv 的 lua 都碰它、每個 player 的 tick 都讀它，所以**在一個播放器上 seek 會把其他所有播放器的濾鏡都拆掉**，還一起等 debounce。兩邊都改成帶 pid，lua 另外在 shutdown 清掉，啟動時掃掉孤兒與舊的共用檔名。
2. **不帶 pid 的管道名，在有兩個以上播放器時不再嘗試。** `\.\pipe\mpvpipe` / `mpvsocket` 對「mpv.conf 寫死 input-ipc-server」的人是唯一入口，所以單一播放器時照試；但兩個播放器時它們是錯的 —— 兩個 pid 解析到同一條管道，濾鏡對其中一個套兩次、另一個完全沒碰到。`tick()` 看到超過一個播放器就傳 `allow_ambiguous=False`。
3. **存起來的 hwdec 改用 pid 當 key。** `ipc.path` 不是身分：沒有乾淨 `remove()` 就退出的播放器會留下條目，下一個拿到同名管道的播放器會被還原成**別人的**舊模式。`apply()` / `remove()` 現在收 pid，`tick()` 的死 pid 清掃順手忘掉離線的播放器。
4. **就緒檢查移出逐播放器迴圈。** 原本在迴圈裡，所以沒有任何播放器連線時迴圈根本不跑：開關翻了、設定存了，**UI 什麼都不說** —— 而這是新裝機器第一個會遇到的狀況。它還是從迴圈裡 `return`，順帶跳過結尾的 `tick()`。
5. **`snapshot_playback` 的 `vf` 只讀一次**（原本 `interpolation_active()` 和 `current_filters()` 各讀一次）。
6. **UI 藏在系統匣時停止輪詢**，回到前景時立刻刷新一次。

**v1.4.4 修的三件事**：

1. **`.vpy` 改成原子寫入。** mpv **每次 seek 都重讀** `fluid_rife.vpy`，而 `apply()` 每次設定變更都重寫它 —— 這是這個程式寫的檔案裡被讀取頻率最高的一個。就地寫入留下一個「mpv 讀到半截腳本」的窗口，而 mpv 對此只會說 `could not init VS`，補幀就這樣無聲停掉。
2. **`config.json` 改成原子寫入。** 寫到一半被中斷會留下截斷的 JSON，`load_settings` 的 `JSONDecodeError` 防護會把它讀成「沒有設定」，**靜默回到出廠預設**。`set_enabled()` 每次切換都寫一次，這個窗口不是假想的。
3. **`python312.dll` 不再寫死。** 這個檢查算在 `core_ok` 裡，所以任何內嵌其他版本 CPython 的 mpv 樹都會被判「尚未就緒」、完全拒絕補幀，而錯誤訊息指向 Python 而不是那個版本釘選。改成 glob `python3*.dll`。版本釘選屬於 `install_vapoursynth`（R70 wheel 是 cp312），不屬於就緒判定。

**v1.4.3 修的五件事**：

1. **常駐系統匣時不再全速輪詢。** `tick()` 每 0.3 秒都會掃 engine cache 目錄、重跑 `diagnose()`、要 GPU 快照 —— 沒開任何播放器時也一樣。改成有播放器 1 秒、閒置 5 秒（`HOUSEKEEPING_ACTIVE` / `HOUSEKEEPING_IDLE`）。
2. **執行期改設定會繞過驗證** —— 夾限只在 `Settings.from_dict`（載入時）跑，所以同一份設定重開前後行為不同。`update_settings()` 現在走同一條驗證。
3. **管道比對用 pid 子字串**，pid 234 會match 到 12345 的 socket，導致兩個 PlayerProcess 共用一條連線。新增 `pipe_names_pid()` 整段比對。
4. **單一實例判定**改用 `WinDLL(..., use_last_error=True)`。
5. **設定目錄是磁碟根目錄時產生的 .vpy 無法編譯**（raw string 不能以反斜線結尾）。改用 `as_posix()`。

測試：`py -3.10 -m pytest` 在 `C:\projects\Fluid_Motion_Player`，**140 passed**（v1.4.3 / v1.4.4 / v1.4.5 各新增 5、5、7 個回歸測試）。AX Player 沒有測試框架，改動用一次性腳本驗證。

v1.4.4 那 5 個測試都確認過會對修補前的程式失敗 —— 特別是原子寫入那兩個：斷言「例外之後舊檔還在」是不夠的，例外在寫入開始前丟出時就地寫入的版本也會過，所以測的是**內容被寫到哪裡**（暫存 sibling 再 `os.replace`，而不是目的檔本身）。

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

**已在 v1.1.5 結案（見 §1.1），根因是 `env` 參數。** 下表保留當初排除掉的假設，其中最後兩列**當時的理由是錯的**，一併標出來免得再被引用。

| 假設 | 為什麼排除 |
|---|---|
| GPU 解碼資源被佔滿 | 30 個 mpv 同時抓幀，thumbfast 式啟動 **0/6 失敗**（那些是 Python 的 `subprocess.run`，不帶 `env`，所以本來就不會失敗） |
| 快速重啟搶不到具名管道 | 共用同一 socket 連續啟動 **10/10 成功** |
| 路徑被 script-opts 切壞 | hook 到的 cmdline 完整正確，檔案存在 |
| `spawn_first=yes` 可以解決 | 確實不能解決，但**理由是錯的** —— 冷啟動不是變因，密集度才是 |
| 「其實是假陽性，子行程有啟動」 | `CreateProcessW` 回 FALSE / err 87，系統上沒有對應行程 |
| 「只有無 console 的 GUI 行程會遇到」 | ~~最小重現 `py` 成功 / `pyw` 失敗~~ —— **不成立**，有 console 的 host 帶 `env` 一樣 8/8 失敗，那組對照差在時序 |
| 重試次數不夠 | ~~第一次重試就成功~~ —— **不成立**，A/B 對照下帶 `env` 是 100% 失敗，重試再多也沒用。結論（別調 `SPAWN_RETRY_LIMIT`）碰巧是對的 |

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
2. **測量工具本身會騙人。** 這一輪至少五次得到無效數據，最貴的一次是 1.2 節那個不存在的問題 —— **在 Windows 上用檔案大小判斷「有沒有寫入」是不可靠的**，要讀內容。另外 python-mpv 的 `command("subprocess", args=[...])` 會把 list 序列化成字串塞進 argv[0]，用它做的 subprocess 實驗全部無效 —— 但**不必**因此只能讓 thumbfast 自己去 spawn：直接對 libmpv 的具名管道寫 raw JSON（`{"command": {"name": "subprocess", "args": [...], "env": [...]}}`）就繞過了那個 binding，而且可以逐一控制參數。v1.1.5 的根因就是這樣隔離出來的。
3. **間歇性問題不能用單次觀察下結論。** v1.1.1 就是憑一次「沒出現」就發版，然後被推翻。
4. **修好之後要驗證它真的會執行。** thumbfast 重試的第一版條件寫成 `success == false`，語法正確、載入正常，但**永遠不會觸發**。
5. **要看 mpv 內部到底做了什麼，可以 hook libmpv 的 IAT。** 這一輪就是這樣拿到 `CreateProcessW` 的真實回傳值和 `GetLastError` 的。做法：解析已載入模組的 import table，`VirtualProtect` 後改寫該 slot 指向 `ctypes.WINFUNCTYPE` 包出來的 Python 函式，轉呼叫原函式並記錄。
6. **一個正確的觀測，接上錯誤的解釋，比沒有觀測更貴。** IAT hook 量到的 `err 87` 完全正確，錯的是建立在它上面的那一串推論（暫時性、console、縮圖正常），而那串推論後來被寫進 HANDOFF、README 和原始碼註解，變成三個地方都要改。**觀測寫下來，解釋標成假設。**
7. **A/B 對照要能區分兩種失敗模式，否則等於沒測。** v1.1.2 拿「指向一個啟動不了的檔案」驗證重試，看到「兩次靜默重試然後報錯」就收工 —— 但那個畫面同時符合「預算正確用盡」和「預算永遠回不來」。要區分就得讓**只有被測的那一個變因**改變（後來的做法：同一個 host、同一段 burst，只差 `env` 有沒有傳）。
8. **原子寫入的測試不能只斷言「例外之後舊檔還在」。** 例外在寫入開始前丟出時，就地寫入的版本也會通過。要測的是**內容被寫到哪裡** —— 攔 `Path.write_text`，斷言它拿到的不是目的檔。`tests/test_config_runtime.py` 的 `_writes_land_on()` 就是幹這個的。
9. **量，不要憑直覺列效能問題。** §7 有一整張表是我列了、量完全部撤回的。挑出來的那五條沒有一條成立，而真正該修的全是正確性問題。**先量再列。**
10. **撤回要跟主張一樣嚴謹。** `.part-` 那條我先誇大（說會累積），被質疑後又**錯誤撤回**（理由是「窗口只有 1.33 毫秒」）—— 兩次都沒讀清楚自己寫的錯誤處理。真正的觸發條件是一條普通的錯誤返回路徑。**推翻一個發現，跟提出它一樣需要證據。**
11. **修法也要量，不只量問題。** 關閉噴錯的直覺解法（`waitForDone()`）會把一行日誌換成 30 秒的關閉凍結。量了才知道要改用「clear + 守住 emit」。
12. **測試自己也會 flaky，而且會裝成產品的 bug。** v1.4.5 有一個回歸測試寫成「剛寫的 seek hold 檔應該讀作 held」—— NTFS 的 mtime 是 100ns、`time.time()` 是 ~15ms，檔案可以讀起來稍微在未來，`0 <= age` 的防護就說「沒有 held」。改成用 `os.utime` 明確蓋時間戳。**看到測試偶爾失敗，先懷疑測試。**

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

沒有已知的未解問題。

### 曾列在這裡、v1.1.6 / v1.4.5 已經做完的

`debug.log` 輪替、`snapshot_playback` 的 `vf` 只讀一次、UI 藏在系統匣時停止輪詢、contact sheet 原子寫入 —— 都在那兩版裡了。

### 量過之後撤回的「效能問題」

**這幾條是我照直覺列的，量完全部不成立。** 留著是為了不要有人再列一次：

| 當時的說法 | 實測 |
|---|---|
| 閒置時每 0.3 秒列舉全系統具名管道，「四者裡最貴的」 | `os.listdir(\.\pipe\)` 在 548 條管道下 **0.76 ms** → 152 ms/分鐘。process scan 0.97 ms → 194 ms/分鐘。閒置 tick 加 housekeeping 總共 **0.41 秒/分鐘 ≈ 單核 0.7%** |
| `Sidebar.set_playing()` 對每列 `setData()`，「一千個檔案就是一千次重繪」 | 3000 列 **0.48 ms**，而且只在換檔時跑一次 |
| `_apply_filter()` 每次按鍵掃全部項目，該 debounce | 3000 列每次按鍵 **3.05 ms** |
| `roaming_dir()` 每秒 20 次多餘 mkdir | 一次 **0.061 ms** → 70 ms/分鐘 |
| `%APPDATA%\FluidMotion\downloads` 數 GB 永遠不清 | **那個目錄在這台機器上不存在** —— `C:\mpv` 是手工組的，bootstrap 從沒跑過。程式裡是真的，但沒有觀察到 |

`engine_cache.info()` 是單次最貴的（4.76 ms，53 檔 / 0.86 GB），但它跑在 5 秒的閒置節奏上 —— v1.4.3 已經處理過了。

### code-review 找到的五個，量完只剩三個（v1.1.7）

`/code-review high` 掃 `ax_player` 產出五個。**逐條驗證之後，兩個不成立、一個我原本的撤回是錯的、一個我原本提的修法會製造更糟的問題。**

| 發現 | 驗證結果 |
|---|---|
| 關閉時 emit 到已銷毀的 signals | **真的，已修**。8 個檔案關不出來；60 個未快取、800ms 關 → 每次都噴。8/25 那 12 筆是 `0c85744`（無上限預產）時代的，v1.1.4 的 12 個上限讓它變罕見但沒消失 |
| 失敗的預覽圖每次 hover 重跑 | **不成立**。截斷檔 / 只有檔頭 / 非影片都在 `probe_duration` 就失敗 → **0.09 秒**。最壞的實際情況（有音軌沒視訊，九次 fallback 全跑）**1.30 秒**。20 秒逾時不會觸發 —— 沒東西可解碼時 mpv 立刻退出。而且它取代的舊行為更糟（popup 永遠卡住） |
| 開資料夾白做 12 張解碼 | **不成立**。16.5 毫秒，一次。低於撤回其他效能項時用的同一把尺 |
| `.part-` 檔累積 | **我第一次撤回錯了，已修**。當時說「要當機卡在 1.33 毫秒窗口」—— 窗口不是重點。`QImage.save()` 磁碟滿／權限不足是**回傳 False 不丟例外**，而我只在 `except OSError` 裡清。實測留下 353 bytes，且通過現有全部三種清理 |
| 遞迴模式拖曳未掃描的檔 | **真的，已修**。實測媒體庫被換成 `C:\V\Sub` |

**修法本身也量過。** 關閉噴錯的直覺解法是 `waitForDone()` —— 實測：12 個排隊 × 1.2 秒 → 1.21 秒；但**其中一個抓幀卡到 `GRAB_TIMEOUT` 就是凍結 30 秒**。拿一行日誌換關閉凍結半分鐘不划算。改成 `clear()`（只丟沒開始的）+ 在 `run()` 裡守住 emit。

### 查過、判斷不值得動

1. **`probe_duration` 的結果沒有快取。** sheet 被 LRU 淘汰後重新產生要重問一次長度。加了 `EAGER_SHEET_LIMIT` 之後量級已經從幾百次降到 12 次，收益很小，而且會多一個要失效的快取檔。
2. **`EAGER_SHEET_LIMIT = 12` 是拍的，不是量的。** 側欄一列 79px，預設視窗大約看得到 6 列，抓了兩個畫面的量。要調就調數字，不要改成「跟著捲動產生」—— 那會把無上限產生換個地方放回來。
3. **快取的 LRU 依賴 `st_atime`。** 曾懷疑 Windows 預設不更新 atime 會讓它退化成 FIFO —— 實測這台是 `DisableLastAccess = 2 (System Managed, ENABLED)`，atime 確實有更新（thumbnails 的 atime 與 mtime 相差兩天）。**不是問題。**
4. **`.vpy` 用畫面尺寸猜色彩矩陣**（`est_matrix = 1 if is_hd else 5`），BT.2020 / HDR 片源開補幀會偏色。是真的，但要正確修得從 frame props 讀，而使用者不看 HDR。
5. **把 IPC 改成 pipeline**（`snapshot_playback` 16 個 round-trip → 1 個，mpv 忙時約省 230ms/tick）。收益真實，但那是 133 個測試圍著的核心路徑，改動面大。先做上面第 3 項就好。
6. **`fluid_motion` 的死碼**（`enumerate_windows_pipes` / `exit_duplicate` / `fps_fraction_label` / `project_root`）。其中 `debug_log_path()` 是**刻意**留的，`cf33d83` 的 commit message 有寫。

### 還有兩個「知道就好」的環境事實

1. **`player_widget.py` 設的 `input_ipc_server` 不會贏過 `mpvSockets.lua`。** 實測用 `mpv.MPV(input_ipc_server="axtest-con", config_dir=r"C:\mpv")` 起 host，真正建立的管道是 `%TEMP%\mpvSockets\<pid>` —— mpv 在 option 執行期被改時會**重新綁定**，所以後設的贏，`2f6f49c` 想達成的目標其實沒達成。不影響功能：Fluid Motion 的 `6faf4c3` 早就加了 mpvSockets fallback。註解已在 v1.1.5 更正。
2. **`C:\mpv\scripts\mpvSockets.lua` 每次啟動報錯一次**（`debug.log` 裡 104 筆，cp950 解出來是「命令語法不正確。」）。它跑 `cmd /c mkdir`，路徑組壞了。既然 AX Player 自己設 `input_ipc_server`、`zz-fluid-ipc.lua` 也設，它在這台機器上其實多餘 —— 移掉可同時解決搶綁定和日誌噪音。那是第三方腳本，不在任一 repo 內。

### 維護提醒

**thumbfast 是 vendored patch。** 日後更新 thumbfast 要重新套用三處修改（拿掉 `env`、per-attempt 重試、拿掉 OSD 橫幅），檔案裡有 `AX Player patch:` 註解標示位置，而且 `mpv-runtime/scripts/` 和 `C:\mpv\scripts\` 兩份都要改。
