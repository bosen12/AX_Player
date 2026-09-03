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

目前版本：**AX Player v1.1.9**、**Fluid Motion v1.4.7**，都已 commit、push、build、部署、發 release。

**上一版這句話有一半是錯的**：v1.1.8 的 tag 確實推上去了（指向 `b1be307`），但 **GitHub 上從來沒有 v1.1.8 的 release**，連草稿都沒有 —— 上一輪的發布那一步沒有成功，而這份文件寫成做完了。08-29 查 `gh release list` 才發現。已決定不補發，v1.1.9 直接取代它。**發完 release 要用 `gh release list` 看一眼**，不要憑印象寫進這裡。

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
| v1.1.8 | 補上測試框架（15 個，涵蓋 v1.1.5–v1.1.7 的修正） |

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
| v1.4.6 | code-review 找到 v1.4.5 自己引入的三個問題，外加撤回一個從沒生效的改動 |

**v1.4.6 修的四件事**（**全部來自 v1.4.5 那一次改動本身**，不是舊有缺陷）：

1. **連線失敗的一拍不再忘掉還活著的播放器的 hwdec。** 死 pid 清掃用的是 `live`（這一拍有回應），不是「行程沒了」。其他清掉的東西都救得回來（`_applied` 掉了下一拍重套），唯獨 hwdec 救不回來 —— `ensure_copyback_hwdec` 看到已經是 copy-back 就提早 return，不會重新記錄。所以**一次連不上（mpv 忙著編譯 TensorRT 引擎時管道不回應）就永久失去原始模式**，之後關掉補幀，播放器會**永遠停在 auto-copy**，背著 GPU→CPU 傳輸卻沒有濾鏡 —— 正好是那段註解說要避免的成本。改成對 `iter_mpv_processes` 真的看到的 pid 清掃。
2. **seek hold 讀不到新檔名時，退回讀 v1.4.5 之前的共用檔名。** `install_lua` 只改磁碟上的檔，**已經在跑的 mpv 記憶體裡還是舊腳本**（mpv 啟動時才載入腳本）。實測 `C:\mpv\scripts\zz-fluid-ipc.lua` 當時仍是舊的共用名，而 watcher 找 `seek_hold-<pid>` —— 那個播放器的 hold 永遠找不到，0.15 秒的 debounce 消失，mpv 一清掉 `seeking` 下一拍就重套濾鏡，拖進度條時每個間隔都重建一次管道。
3. **啟動時的清掃不再刪掉還在用的 hold。** 原本不看時間全刪，所以在別人拖進度條的當下啟動，會刪掉人家剛寫的 hold，第一拍就可能把濾鏡套進 seek 中間。改成只刪超過 `SEEK_HOLD_MAX_AGE` 的。
4. **撤回 UI 的輪詢 gate。** v1.4.5 用 `document.hidden` 擋住 0.9 秒的輪詢 —— **那個判斷從來沒有成立過**：pywebview 的 `hide()` 只藏原生視窗，不會通知 WebView2 的 document。實測 100ms 計數器在 `hide()` 前後與 `show()` 之後都回報 `hidden=false` / `visibilityState="visible"`，而且一直在跑。從 Python 端驅動做得到，但閒置的 `get_state()` 實測 **0.200 ms**，整個節省是 **13.4 ms/分鐘** —— 比撤回其他效能項時的數字還小一個數量級。所以是移除，不是重做。

**v1.4.5 修的六件事**（前四件只有同時開兩個播放器才踩得到，這也是它們活這麼久的原因；v1.4.3 修的 pid 子字串誤配是同一家族的第一個）：

1. **seek 的 hold-off 改成逐播放器。** 原本是一個共用檔：每個 mpv 的 lua 都碰它、每個 player 的 tick 都讀它，所以**在一個播放器上 seek 會把其他所有播放器的濾鏡都拆掉**，還一起等 debounce。兩邊都改成帶 pid，lua 另外在 shutdown 清掉，啟動時掃掉孤兒與舊的共用檔名。
2. **不帶 pid 的管道名，在有兩個以上播放器時不再嘗試。** `\.\pipe\mpvpipe` / `mpvsocket` 對「mpv.conf 寫死 input-ipc-server」的人是唯一入口，所以單一播放器時照試；但兩個播放器時它們是錯的 —— 兩個 pid 解析到同一條管道，濾鏡對其中一個套兩次、另一個完全沒碰到。`tick()` 看到超過一個播放器就傳 `allow_ambiguous=False`。
3. **存起來的 hwdec 改用 pid 當 key。** `ipc.path` 不是身分：沒有乾淨 `remove()` 就退出的播放器會留下條目，下一個拿到同名管道的播放器會被還原成**別人的**舊模式。`apply()` / `remove()` 現在收 pid，`tick()` 的死 pid 清掃順手忘掉離線的播放器。
4. **就緒檢查移出逐播放器迴圈。** 原本在迴圈裡，所以沒有任何播放器連線時迴圈根本不跑：開關翻了、設定存了，**UI 什麼都不說** —— 而這是新裝機器第一個會遇到的狀況。它還是從迴圈裡 `return`，順帶跳過結尾的 `tick()`。
5. **`snapshot_playback` 的 `vf` 只讀一次**（原本 `interpolation_active()` 和 `current_filters()` 各讀一次）。
6. ~~**UI 藏在系統匣時停止輪詢**~~ —— **v1.4.6 撤回，那個 gate 從來沒有生效過**（見下）。

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

測試：`py -3.10 -m pytest` 在 `C:\projects\Fluid_Motion_Player`，**144 passed**（v1.4.3 / v1.4.4 / v1.4.5 / v1.4.6 各新增 5、5、7、4 個回歸測試）。AX Player 從 v1.1.8 起也有了：`py -3.10 -m pytest` 在 `C:\projects\AX_Player`，**15 passed**（0.2 秒）。裝依賴用 `requirements-dev.txt`。

`tests/conftest.py` 會把 `LOCALAPPDATA` 導向 tmp_path 並重設三個模組級快取（`debug_log._log_path`、`settings._store`、`resume._cache`）—— **沒有它，跑測試會 prune 掉跑測試的人自己的快取**。今天手動驗證時就污染過真實快取兩次、共 80 筆死資料要手動找出來刪。Fluid Motion 的 conftest 也是因為同樣的事才存在的。

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
11. **宣稱「已修」之前要確認它真的會生效。** v1.4.5 的 UI 輪詢 gate 依賴 `document.hidden`，而 pywebview 隱藏視窗時那個值不會變 —— 沒有驗證就寫進了 commit、release notes 和這份文件三個地方。跟 thumbfast 那件事同一個形狀：**觀測沒做，結論先寫**。
12. **review 自己寫的程式碼，命中率會比 review 舊碼高很多。** `/code-review` 掃 `ax_player`（大多是舊碼）五個裡兩個不成立；掃剛改完的 `fluid_motion` 四個裡三個是真的，而且全部來自那次改動本身。**改完就審，趁還記得為什麼那樣寫。**
13. **修法也要量，不只量問題。** 關閉噴錯的直覺解法（`waitForDone()`）會把一行日誌換成 30 秒的關閉凍結。量了才知道要改用「clear + 守住 emit」。
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

### 08-31 這一輪：深度檢查後修掉的

一次側欄／片庫的全面檢查。每一條都先驗證再改，改完都有回歸測試，而且**每個測試都用突變測試確認過真的抓得到**（把修法改回錯的，看測試會不會紅）。

| 修的東西 | 實測 |
|---|---|
| **按「移除選取」之後整個側欄的縮圖永久消失** | `remove_from_playlist` 會 `set_items` 重建整張清單 → 每個 item 的 `PIXMAP_ROLE` 全丟 → 重繪時重新要圖 → `request_thumbnail` 看到路徑已在 `_requested_thumbs` 裡直接 return。**工作永遠不會排隊**，只有重開資料夾才會恢復。改成 `Sidebar.remove_rows()` 用 `takeItem` 只拿掉那幾列，順便解掉捲動跳頂端、搜尋框被清空、選取全失 |
| **篩選之後「移除選取」會刪掉看不見的列** | Qt 不會因為 `setHidden` 就取消選取（實測：hide 之後 `selectedItems()` 仍是三個）。選 3 列→打字篩選→畫面剩 1 列，但計數仍說「已選取 3 項」，按下去移除兩個看不見的。`_selected_paths()` 現在濾掉 hidden |
| **預覽圖 popup 會被螢幕邊界切掉** | sheet 寬 `3*220+4*3` = **672px**，Qt 不會自動修正手動 `move()` 的 ToolTip 視窗。1366×768 筆電上視窗 x > 376 就開始切掉最右一欄 |
| **縮圖以原尺寸常駐記憶體** | 320×180 存進 item，每次重繪才縮到 116×65。外部量測 1000 個**不同**檔案：基準 16.7 MB → **239.5 MB**；先縮到列尺寸則是 59.8 MB。（第一次量被 `QPixmap::load` 內建的 QPixmapCache 騙到——載入同一個檔 1000 次只佔一份，要用不同檔案才量得準。）順手發現 delegate 只開了 `Antialiasing` 沒開 `SmoothPixmapTransform`，縮圖一直是最近鄰縮的 |
| **檔名排序不是自然排序** | `p.name.lower()` 字典序 → `['ep1','ep10','ep2']`。這個播放器就是給動畫資料夾用的 |
| **縮圖固定抓第 3 秒** → 黑畫面／製作商 logo | 改 `--start=10%`。用 bundled 的 mpv 驗過：`--start  Relative time or percent position`，實跑 `--start=50%` 有出圖；100 秒的測試片 10% 與 3s 抓出來 sha 不同。而且百分比必定在檔案範圍內，原本「短於 3 秒就 fallback 到 0 秒」的第二次 spawn 變成真正的例外路徑 |
| **開資料夾永遠從第 1 話開始** | `index = 0` 寫死，而 `mpv.conf` 沒有 `pause`，所以**每次啟動還原上次片庫都會自動播第 1 話**。改成跳過已看完的；啟動還原改成 `reload_player=False`，只列清單不播 |
| 掃描每個檔多一次 stat | `iterdir()+is_file()` 對 `os.scandir`：3000 個本地檔 **47ms → 5ms**。本地這點差距低於這份文件其他項目撤回時用的尺，真正的理由是網路磁碟和遞迴掃描；附帶好處是 `os.walk` 預設不跟隨目錄符號連結，`rglob` 會（junction 迴圈） |
| 副檔名清單漏掉整類片庫 | 補 `.m2ts/.mts/.rmvb/.rm/.3gp/.vob/.ogv/.asf/.divx` 等，mpv 本來就都能播 |
| `0.95` 在 `ui.py` 和 `resume.py` 各寫一次 | 改用 `resume.WATCHED_THRESHOLD` |
| 拖放 URI 解析在兩個檔案各一份 | 抽成 `ax_player/dnd.py` |

新增：側欄右鍵選單（標記已看/未看、檔案總管中顯示、複製路徑）、`F5` 重掃、`Ctrl+O`、標題列視窗置頂鈕、hover 預覽圖上方顯示完整檔名。

`tests/test_sidebar.py` 是新的——側欄過去**完全沒有測試**，上面前兩條就是靠手動測試永遠不會發現的那種 bug。

### 這一輪查過、故意沒做的

1. **`_current` 在播網址時是被 `Path()` 壓壞的字串**（`https://` → `https:/`）。看起來該修，**修了反而會壞**：`set_sort_mode` 用 `reload_player=self._current is None` 判斷，把它改成 `None` 會讓「播網址時改排序」去重載資料夾清單、打斷正在播的網址。維持現狀。
2. **單一執行個體**（從檔案總管連開三個檔 = 三個 process、三份 GPU decode context）。要 `QLocalServer` + 參數轉送，不是順手能做完的，值得單獨開一輪。
3. **排序升／降切換**。自然排序已經解掉實際的抱怨，多一顆按鈕的收益變小了。
4. **列的 tooltip 顯示完整檔名**。hover 已經有 contact sheet popup（ToolTip 型視窗），再疊一個 tooltip 會打架 —— 改成把檔名畫在 popup 上方。
5. **`QFileSystemWatcher` 自動重掃**。播放中自動改清單的互動太意外，`F5` 就夠。

### 這一輪的環境陷阱（都撞到了）

- **§6 說的 heredoc 吃反斜線是真的**：`"\n".join(...)` 寫進檔案變成真的換行，Python 直接語法錯誤。含反斜線的內容一律用 Write/Edit 工具。
- **`ctypes` 預設把 HWND 當 32-bit**：`SetWindowPos` 第一次回 FALSE，就是 64-bit handle 被截掉。一定要設 `argtypes`。
- **`QMenu.exec` 沒辦法從 Python 蓋掉**：測試想 stub 掉它，結果真的開了一個 modal menu 卡在那裡兩分鐘。改成把選單建構拆成 `build_row_menu()`，測試只看它回傳什麼。
- **突變測試自己也會騙人**：第一次跑「把修法改壞、看測試會不會紅」全部顯示 CAUGHT —— 但那個 subprocess 用的是沒裝 pytest 的直譯器，每次都非零退出。**一定要先跑一次不突變的對照組**確認 harness 會回報 PASS。
- 透過 Bash 呼叫 PowerShell 時 `$_` 會被 bash 先展開成 `unsetenv`。要用 PowerShell 工具。

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
**（這一句在 08-29 被修正了一半，見 §8.2：等待並沒有消失，只是搬到視窗消失之後。）**

### 查過、判斷不值得動

1. **`probe_duration` 的結果沒有快取。** sheet 被 LRU 淘汰後重新產生要重問一次長度。加了 `EAGER_SHEET_LIMIT` 之後量級已經從幾百次降到 12 次，收益很小，而且會多一個要失效的快取檔。
2. **`EAGER_SHEET_LIMIT = 12` 是拍的，不是量的。** 側欄一列 79px，預設視窗大約看得到 6 列，抓了兩個畫面的量。要調就調數字，不要改成「跟著捲動產生」—— 那會把無上限產生換個地方放回來。
3. **快取的 LRU 依賴 `st_atime`。** 曾懷疑 Windows 預設不更新 atime 會讓它退化成 FIFO —— 實測這台是 `DisableLastAccess = 2 (System Managed, ENABLED)`，atime 確實有更新（thumbnails 的 atime 與 mtime 相差兩天）。**不是問題。**
4. **`.vpy` 用畫面尺寸猜色彩矩陣**（`est_matrix = 1 if is_hd else 5`），BT.2020 / HDR 片源開補幀會偏色。是真的，但要正確修得從 frame props 讀，而使用者不看 HDR。
5. **把 IPC 改成 pipeline**（`snapshot_playback` 16 個 round-trip → 1 個，mpv 忙時約省 230ms/tick）。收益真實，但那是 133 個測試圍著的核心路徑，改動面大。先做上面第 3 項就好。
6. **`fluid_motion` 的死碼**（`enumerate_windows_pipes` / `exit_duplicate` / `fps_fraction_label` / `project_root`）。其中 `debug_log_path()` 是**刻意**留的，`c51d0d3` 的 commit message 有寫。

### 還有兩個「知道就好」的環境事實

1. **`player_widget.py` 設的 `input_ipc_server` 不會贏過 `mpvSockets.lua`。** 實測用 `mpv.MPV(input_ipc_server="axtest-con", config_dir=r"C:\mpv")` 起 host，真正建立的管道是 `%TEMP%\mpvSockets\<pid>` —— mpv 在 option 執行期被改時會**重新綁定**，所以後設的贏，`2f6f49c` 想達成的目標其實沒達成。不影響功能：Fluid Motion 的 `98bfb8d` 早就加了 mpvSockets fallback。註解已在 v1.1.5 更正。
2. **`C:\mpv\scripts\mpvSockets.lua` 每次啟動報錯一次**（`debug.log` 裡 104 筆，cp950 解出來是「命令語法不正確。」）。它跑 `cmd /c mkdir`，路徑組壞了。既然 AX Player 自己設 `input_ipc_server`、`zz-fluid-ipc.lua` 也設，它在這台機器上其實多餘 —— 移掉可同時解決搶綁定和日誌噪音。那是第三方腳本，不在任一 repo 內。

### 維護提醒

**thumbfast 是 vendored patch。** 日後更新 thumbfast 要重新套用三處修改（拿掉 `env`、per-attempt 重試、拿掉 OSD 橫幅），檔案裡有 `AX Player patch:` 註解標示位置，而且 `mpv-runtime/scripts/` 和 `C:\mpv\scripts\` 兩份都要改。

---

## 8. 08-29 的複查

兩個 repo 都從頭讀過一遍，逐條驗證後改了六處。基準線：AX Player 15 passed → 18 passed，Fluid Motion 144 passed → 145 passed。

### 8.1 改掉的

| 專案 | 問題 | 證據 |
|---|---|---|
| AX | `open_folder()` 不正規化路徑 | 相對資料夾（`run.bat` 的 `%*` 直接透傳）會讓 `_playlist` 存相對路徑，而 m3u8 寫在 `%TEMP%`，**mpv 對 playlist 的相對項目是以 playlist 檔案所在目錄解析**——實測 `Failed to open <temp>/vids/clip.mkv`，整份清單一個都播不了，`last_folder` 還會把相對路徑存起來。另外 `resolve()` 在 Windows 會正規化大小寫（實測 `realcase/clip.mp4` → `RealCase\Clip.MP4`），而 `play()` 有 resolve、`open_folder()` 沒有，大小寫不同的資料夾等於每次點擊都重掃，遞迴模式下還會把媒體庫改根——就是 v1.1.6 修過的那個 bug 的第三道門。修法是 `open_folder` 開頭一行 `resolve()`，對本來就正規的路徑是 no-op |
| AX | 暫停時每 5 秒重寫整個 resume.json | 5 秒輪詢不管暫停與否都跑，`save_progress` 也不比對。實測 5000 筆 = 630 KiB、單次 3.79 ms → 暫停時 7.4 MiB/分的無謂寫入。**CPU 這一面不成立**（0.076% 單核，低於撤回其他效能項的同一把尺），理由只有寫入放大。順帶：影片播到最後 5% 之後 `pos` 固定寫 0.0，現在那段也不再重複寫 |
| FM | `media-title` 被當 HTML 塞進 UI | `renderPlayers` 是全檔唯一一個把外部資料丟進 `innerHTML` 的地方。實測：ffmpeg 給 mkv 寫 `-metadata title='<img src=x onerror=alert(1)>'`，mpv 就原字串回報 media-title。`<img onerror>` 經 innerHTML 是會執行的，而且環境裡有 `window.pywebview.api`（`quit()` / `start_setup()` 觸發 3.5 GB 下載 / `open_engine_cache()` 走 `os.startfile`）。串流更糟——標題來自對方。加了 `escapeHtml()`，用 node 對著真實 payload 驗過：`<img` → `&lt;img`，CJK 標題原樣通過 |
| FM | `python -m fluid_motion` 吞掉離開碼 | `__main__.py` 只有 `main()`。實測 `main()` 回 42 → 行程離開碼 0，修後 42。打包版走 `packaging/launch.py`，本來就是對的 |
| FM | 版本號停在 1.0.0 | git tag 當時已到 v1.4.6，程式裡卻還寫 1.0.0。這一輪隨著發版改成 **1.4.7**。沒有任何 CI 會 bump 它，所以**下次發版要記得手動改** `fluid_motion/__init__.py` 和 `pyproject.toml`（或改成從 tag 推導）。影響只在文件與 wheel 層面，沒有程式讀 `__version__` |
| AX | 根目錄兩個空目錄 `.exe/`、`hi/` | 誤打的指令留下的；git 看不到空目錄所以 status 一直是乾淨的。已刪 |

發完 release 之後又補了一個 **FM 的測試修正**（`e394e0b`，只碰測試、產物沒變，所以 v1.4.7 維持原樣）：`test_build_bat_does_not_report_success_after_a_failed_build` 用的是 `Path("build.bat")` —— **cwd 相對路徑**，所以它讀到的是 pytest 啟動所在目錄的那個 `build.bat`。從隔壁 AX Player 目錄跑就會讀到那一份而 `ValueError`。崩潰還算好的結果：真正的問題是只要某個 `build.bat` 剛好照順序含有那四個字串，它就會綠燈，而 FM 自己的檔案從頭到尾沒被打開過 —— 一個能因為錯誤理由通過的測試比會壞掉的更糟。**這正是這一輪在 `open_folder` 修掉的同一類 bug，往上一層而已。** 兩套測試其餘的讀取都掃過了，全部已經正確錨定在 `Path(module.__file__)`／`resources_dir()`／`ui_dir()`／`roaming_dir()`／`tmp_path`，只有這一處是裸的。修法驗證用的是 mutation：把 `build.bat` 的 guard 拿掉，測試確實會失敗（代表它真的在讀那個檔），事後用 sha256 確認 `build.bat` 完全還原。

另外補了兩處註解：`inject._vf_arg` 把「vf 參數永遠是 `~~/` 相對、而 `~~` 是**播放器自己的** config dir」這個對呼叫端的約束寫明（`apply()` 拿到的 root 必須是 `player_config_dir(ipc)`，否則 .vpy 寫在 A、vf 指向 B，mpv 只會說 could not init VS）；`ui._popup_pos` 的註解原本說 popup「roughly level with the row」，實際是寫死 `y=8`，改成說明為什麼固定錨點才是對的。

### 8.2 修正 §7 的一句話：`clear()` 並沒有讓關閉的等待消失

§7 說「`waitForDone()` 會凍結 30 秒，所以改成 `clear()`」。**前半對，後半不完整。** 實測（QThreadPool + 兩個 sleep 3 秒的工作，先 `clear()` 再 `close()`）：

```
視窗立刻消失
process teardown reached at +0.00s
total wall 3217 ms          (工作 sleep 3000 ms)
```

行程收尾仍然會等 pool 裡**正在跑**的工作。差別是真實的、而且現行做法仍然比較好——視窗確實立刻不見了——但「凍結沒有了」是錯的：它變成一個看不見的幽靈行程，而那正是 `build.bat` 的 robocopy 會抱怨 exe 被鎖住的原因之一。

**沒有改**：`clear()` 已經把排隊的丟掉，剩下的只有 ≤4 個正在跑的，照 §7 自己量的「一個 job 約 1.2 秒」，典型殘留就是 **1.2 秒**（30 秒只發生在抓幀卡死時）。為了 1.2 秒去動抓幀核心不划算。真要解得讓 job 可取消（`_grab_evenly_spaced` 的輪詢迴圈裡看旗標並 kill 子行程），列在這裡當作已知、已量、暫不處理。

### 8.3 量過之後撤回的

**「補幀開著時每次 seek 都會來回切 hwdec 兩次」——不成立。**

我從程式碼推出這條並且用假 IPC 驗證了機制（`remove()` → `restore_hwdec()` → 下次 `apply()` → `ensure_copyback_hwdec()`，一個 seek 週期 3 次 hwdec 寫入）。但實際流程走不到：lua 在 `seek` 事件當下就把 `@fluid` 拿掉，watcher 0.3 秒後 tick 讀到的 `vf` 已經沒有 fluid，`player.interpolation` 是 False，於是只走 `_invalidate()`、**不呼叫 `remove()`**，hwdec 全程維持 `auto-copy`，重新 apply 時 `ensure_copyback_hwdec` 直接 early return。設計是對的。

**但順帶量到一個以前沒記錄的數字：mpv 執行期改 hwdec 會讓播放停頓約 0.65 秒。**（720p h264、`--no-config`，比較媒體時間與牆鐘時間的落差）

```
control (nothing)     media 1.500s / wall 1.517s  -> lost +0.017s
set hwdec=auto-copy   media 0.867s / wall 1.549s  -> lost +0.682s
set hwdec=auto-safe   media 0.833s / wall 1.518s  -> lost +0.685s
control (nothing)     media 1.534s / wall 1.518s  -> lost -0.016s
set hwdec=auto-copy   media 0.900s / wall 1.533s  -> lost +0.633s
set same value again  media 1.500s / wall 1.535s  -> lost +0.035s
```

**設成相同的值幾乎免費**（+0.035s），設成不同值就是一次完整的解碼鏈重建。這筆成本落在每一次 F3／UI 開關補幀上：開一次 0.65 秒、關一次 0.65 秒，全都在濾鏡本身重建時間之外。要不要改成「整個 session 維持 copy-back、不在關閉時還原」是個取捨——我沒有量過 copy-back 在正常播放時的實際代價，所以不給結論，只留數字。

### 8.4 查過、判斷不值得動

1. **診斷面板的 nvidia-smi job 和縮圖共用 `_thumb_pool`。** 面板開著又剛好四個 sheet 在跑時，GPU 讀數會停在幾秒前。但 `GpuQueryJob` 是預設優先權、eager sheet 是 -1，所以它只等**正在跑**的那四個 ≈ 1.2 秒，也就是一個輪詢週期。不值得多開一個池。
2. **`inject._vf_arg` 那個沒用到的 `script` 參數。** 本來想拿掉，但 `test_vf_arg_uses_label` 是帶著參數呼叫並斷言 `"C:" not in arg` ——那個參數不是疏漏，測試刻意在記錄「路徑一律走 `~~/`」。改成補註解說明約束。
3. **`bootstrap._download` 失敗時留下 `.part`。** AX Player 的 `mpv_fetch._download` 已經用 `finally` 清掉，FM 沒有。但那個檔從不被讀（判斷用的是 `dest` 不是 `tmp`），重試會覆蓋，而且 §7 已經確認 `downloads` 目錄在這台機器上根本不存在。
4. **lua `write_hotkey` 與 watcher 讀取之間的 truncate race。** mpv 以 `"w"` 開檔（截斷）到寫入之間，watcher 若剛好讀到會拿到空字串、按鍵掉一次。窗口是微秒級，`HOTKEY_POLL` 是 50 ms。

### 8.5 沒有動，因為那是你的決定 —— **09-04 已處理,見 §9.6**

**Fluid Motion 的 repo 裡 commit 了一份 126 MB 的 mpv。** `mpv/` 共 96 個檔案，`mpv/mpv.exe` 109 MB 走 Git LFS（`.git/lfs` 105 M），其餘約 16 MB 是一般 git 物件。

已確認**沒有任何東西讀它**：`mpv_root_candidates()` 找的是 `C:\mpv`／ProgramFiles／`~/mpv`／AXPlayer runtime／scoop／chocolatey／PATH，不含 repo 內的 `mpv/`；`FluidMotion.spec` 的 `datas` 只有 `fluid_motion/ui` 和 `fluid_motion/resources`；測試也沒碰。GitHub 免費 LFS 是 1 GB 儲存／1 GB 頻寬每月，大約十次 clone 就滿。

AX Player 的做法是對的（binary 不進版控，`setup_mpv.py` 現抓）。但把它從歷史移除要 rewrite history，會影響任何已經 clone 的人，而且已經 push 出去了——**這不是我該自己決定的，等你說。** 只加 `.gitignore` 沒有用，那只讓未來的 commit 乾淨，105 MB 的 LFS 物件還在。

---

## 9. 09-03 這一輪：AMD 後端，與一次全面的效能量測

### 9.1 找到並修掉的（AMD 後端本身之外）

AMD 支援的實作分成五層，細節在 `Fluid_Motion_Player/CLAUDE.md`。這裡只記那一輪順帶挖出的**狀態機缺陷**，因為它們與後端無關、只是被後端這個新變數照出來：

| 問題 | 證據 |
|---|---|
| **IPC 讀取失敗被誤判成「濾鏡掉了」** | `vf_is_fluid(None)` 是 `False`，與「沒有濾鏡」無法區分。正在編譯 TensorRT engine 的 mpv 讀不到 `vf`，於是每個 `APPLY_RETRY_BACKOFF` 就被塞一次新濾鏡——最沒餘裕的時候。而且必定發生：全預設快照下 `target_multi` 對 `2x/3x/4x` 根本不看 fps，一律回 >1。改成 `snapshot_playback` 另外回報 `vf_ok` |
| **後端改變時不會重新套用** | `_filter_key` 的 docstring 是「everything that changes the generated .vpy」，而 backend 不在裡面。實測重現：濾鏡已載入、只有解析結果變動時，tick 認為 key 沒變 → mpv 繼續跑舊後端，而面板顯示新的。從 UI 切換剛好會繞過它（`set_enabled` 先 `_invalidate`），所以手動測永遠是好的 |
| **後端在單一操作內被解析多次** | `_apply_to` 先建 key、再等 apply 鎖（mpv 重建 pipeline 時是數秒）、然後才寫檔，兩端各解析一次。實測：key 記 `trt`、檔案寫 `ncnn`。等廠商集合回穩，key 又對上了 → **永久失同步**。現在整條路徑一個操作解析一次往下傳 |
| **缺 Vulkan 時被判定就緒** | ncnn 的就緒檢查只驗 `vsncnn.dll`。Vulkan loader 來自顯示卡驅動、裝不了，缺了會在濾鏡建構後才失敗 |

### 9.2 這一輪量到的數字（HANDOFF 先前沒有的）

**沒有一項需要動。** 記在這裡是為了下次不用重量，也不要有人憑直覺再列一次。

| 路徑 | 實測 | 節奏 | 判斷 |
|---|---|---|---|
| `ui.set_items(3000)` | 17.2 ms | 開資料夾一次 | 感覺不到。profile 顯示成本分散在 Qt 的 `addItem`/`setData`，沒有異常熱點 |
| `_RowDelegate.paint()` | 0.037 ms/列 | 捲動每幀 | 8 列可見 → 一次完整重繪 0.30 ms；60fps 連續捲動 ≈ **單核 1.8%** |
| `natural_key` ×3000 | 5.65 ms | 掃描一次 | 在背景執行緒，不擋 UI |
| `_sort_playlist(3000)` | 9.05 ms | 掃描一次 | 同上 |
| `resume.save_progress` | 1.125 ms（220 筆） | 播放中每 5 秒 | 13.5 ms/分。CPU 面不成立，§8.1 早已判定爭點是寫入放大而非 CPU |
| `cache_key()` | — | 每張縮圖 | 只雜湊「路徑+大小+mtime」字串，**不讀檔案內容**。本來就便宜 |
| FM `tick()` 穩態 | 0.688 ms | 0.3 秒 | **137.7 ms/分**。主導的三項（每 tick 3 次 `mkdir`、5 次 `stat`、1 次 `io.open`）§7 全部量過並撤回；該節自己接受的閒置成本是 410 ms/分 |

**`_apply_filter` 的複驗。** 這一輪量到 4.98 ms/按鍵，比 §7 記的 3.05 ms 高。用同等條件（短檔名）重量是 **3.70 ms**——差異來自檔名長度與機器變異，不是回歸。結論不變。

### 9.3 量過之後修的一項（理由不是速度）

**`Sidebar.set_playing()` 從 0.48 ms 變成 4.05 ms**（3000 列），是 v1.3.0 無障礙那輪引入的：`refresh_accessible_text` 被放進「走訪每一列」的迴圈。

按這裡的尺**它不該動**——只在換片時跑一次，不是輪詢。修的理由是那 2998 列重算出來的字串跟原本一模一樣,**那些工作不可能改變任何東西**。改成只重建狀態真的變動的兩列後是 0.92 ms；`setData` 仍無條件執行，重繪行為不變。

回歸測試蓋的是這類優化最容易漏的那一半:**停止播放的那一列**。少了它，換掉的檔案會繼續對螢幕報讀器宣稱「播放中」。

### 9.4 這一輪的方法論教訓

1. **子代理會把這份文件的「已撤回／不值得動」清單當成新發現抄回來。** 實際發生過:一輪 12 項裡有 4 項是逐字抄自 §7，另有 2 項把 Fluid Motion 的符號（`snapshot_playback`、`est_matrix`）掛到 AX 名下。要求它們**先從程式碼形成結論、最後才讀 HANDOFF 做交叉比對**，並為每條標註 NEW / ALREADY-FIXED / ALREADY-DECIDED-AGAINST，能有效擋掉。
2. **測試會偷偷依賴跑測試那台機器的硬體。** `diagnose()` 變成依後端分流之後，既有測試的結果開始取決於執行機器上有沒有 NVIDIA 卡；ncnn 的斷言則取決於有沒有裝顯示卡驅動（Vulkan）。兩者都改成由測試自己 pin。
3. **斷言 UI 原始碼字串時要先剝掉註解。** 修正的註解引用了它取代的舊字串，於是測試比對到自己的註解而失敗——為錯誤的理由。
4. **`[hidden]` 屬性在現代 Chromium 是 `!important` 的。** 我曾斷言 `.cache-panel { display: flex }` 會蓋掉它、讓隱藏失效，實機測試後**撤回**:作者的一般宣告蓋不過 UA 的 `!important`,只有作者自己加 `!important` 才行。

### 9.5 09-03 後半：AX 兩個從未有測試的模組

兩個模組都是整份讀完才找到的,不是抽樣猜的。共同點:**它們都沒有任何測試**。

| 問題 | 證據 |
|---|---|
| **誤拖一段文字會清空播放清單** | `has_uris()` 刻意對任何文字放行(拖曳純文字 URL 只會設 `text/plain`,在 dragEnter 拒絕等於沒有回饋),但下游沒有再檢查那是什麼。`QUrl.isLocalFile()` 對「真網址」和「無法辨識的東西」都是 False,所以隨機文字落進 `play_url()` —— 而那會發 `loadfile replace`。實測:`QUrl('hello world')` scheme 為空 → 走 play_url |
| **拖曳純 Windows 路徑文字被當網址** | `QUrl('C:/Videos/ep1.mkv')` 把**磁碟機代號解析成 scheme**(實測 scheme = `'c'`),`isLocalFile()` 因此是 False。判別方式:**單字元 scheme 就是磁碟機代號**,實務上沒有 scheme 只有一個字母。`dnd.classify()` 現在回答「這是什麼」,無法辨識就忽略 |
| **多開時觀看進度會整批消失** | 每個 process 把整份資料庫留在記憶體並整份寫回,所以最後寫的人會把別人的條目全部蓋掉。**三個 process 各存 400 部,實測丟失 792 / 1200**;加上寫入前與磁碟合併後降到 **5**。§7 早就記載「從檔案總管連開三個檔 = 三個 process」,所以兩個視窗看兩集,其中一集的進度會安靜地不見 |
| **`resume.json.tmp` 是固定檔名** | 每個並行 process 都會挑到同一個暫存檔:一個可以把另一個正在寫的檔案截斷,然後把半成品 `os.replace` 蓋到真的資料庫上 —— 正是那個原子寫入存在要防的事。Fluid Motion 的 `save_settings` 一直都帶 pid,AX 這邊沒有 |

**合併的成本量過了。** 1000 筆時 `save_progress` 5.66 ms → 5 秒輪詢下 **67.9 ms/分**,落在撤回其他效能項的區間下緣。而且加的是**讀取**不是寫入,所以 §8.1「爭點是寫入放大而非 CPU」那個論證不受影響。

**方法論**:含反斜線的測試字串一律用 `chr(92)` 組出來,不要寫字面值。查 UNC 路徑那條時,shell 吃掉了測試輸入的反斜線,讓一個正確的分類器看起來是壞的 —— §6 早就警告過這個環境會這樣。

### 9.6 09-04:§8.5 的 126 MB LFS,處理完了

擁有者拍板後執行。**時機是理由的一部分**:當時 0 star、0 fork、沒有人 clone 過,所以改寫歷史的實際代價是零。等有使用者之後再做,就是要所有人重新 clone。

`git filter-repo --path mpv/ --invert-paths` 掃過全部 60 個 commit。**不是只在 tip 刪掉**——那樣每個 clone 還是會把 110 MB 的 LFS 物件拉下來。

| | 之前 | 之後 |
|---|---|---|
| pack 大小 | 8.61 MiB | **259 KiB** |
| LFS 物件 | 110 MB | **0** |
| commit / 標籤 | 60 / 19 | 61 / 19(全數保留) |
| **乾淨 clone** | ~119 MB | **993 KB / 2 秒,`.git/lfs` 根本不存在** |

從 clone 出來的 repo 跑測試:**226 passed**。所以它不只是變小,是真的可用。

**已驗證沒有被弄壞的:**

- 全部 18 個 release 與其資產完好。標籤改寫移動了指向的 commit,但 GitHub 的 release 綁的是**標籤名稱**、資產另存 —— 這點事前只是推斷,事後查證過了。
- 那 110 MB 仍在本地 `.git/lfs`,加上一份含全部 ref 的 bundle 備份。檔案本身沒有消失。

**改寫的附帶成本,以及怎麼補的:** 這份文件引用了三個 FM 的 commit 雜湊,改寫後全部失效。`filter-repo` 會產生 `.git/filter-repo/commit-map`,照著更新即可 —— 而且每個新雜湊都回頭確認過指向**相同的 commit 主旨**,不是只看對應表就算數:

    cf33d83 -> c51d0d3    debug_log_path() helper
    6faf4c3 -> 98bfb8d    mpvSockets pipe detection
    268427f -> e394e0b    build.bat test anchoring

`filter-repo` 會自動修好被改寫 repo **自己** commit 訊息裡的雜湊引用,但跨 repo 的引用它碰不到。兩個專案互相引用時要記得這件事。

**一件仍未確定的:** 強制推送移除的是 LFS 物件的**引用**,GitHub 端的儲存可能還留一段時間,要完全清除通常得開 support ticket。但計費看的是**傳輸**,而乾淨 clone 已證實不再拉取,所以實際的頻寬上限問題已經解決。

### 9.7 09-04:FM 兩個大檔逐行讀完,五個缺陷

`watcher.py`(1025 行)與 `inject.py`(784 行)是四個大檔裡最後、也是密度最高的兩個。這一輪逐行讀完,找到的五個都不是靠直覺列的——每一個都先量或先驗證可達性,再改,再突變驗證。

**1. `stop()` 不是屏障。** 它設事件、拆濾鏡就返回,三條迴圈執行緒都是 daemon 且沒有人 join;`app.py` 接著才拆托盤與 webview,最後才 `os._exit(0)`。所以飛行中的 tick 會在這段空窗裡跑完,而且:

- `tick()` 第一件事就是寫心跳,於是它把 `stop()` 剛刪掉的檔案寫了回去(實測重現)。lua 的 `strip_stale()` **只在載入檔案時跑,沒有週期性 timer**——這點是讀 lua 才確定的,原本以為是 4 秒後自動清。真正的後果因此是:退出後四秒內開下一個檔案,濾鏡不會被拆。
- `_apply_to` 與 `stop()` 的 remove 都走 `_apply_lock`,但鎖不決定順序,排在後面的 apply 會把濾鏡裝回去。

守衛加在 `_write_heartbeat` 開頭與 `_apply_to` **取得鎖之後**——要擋的正是「排到 stop() 後面」那一種。

**2. `_bootstrapping` 在新執行緒上才設。** `start_bootstrap()` 在 `.start()` 之後立刻返回,bridge 隨即以 `get_state()` 回答 `running=false`,而 UI 的安裝鈕只從這個輪詢狀態 disable。窗口只有一次 thread start,**沒有在實務上觀察到**;但代價是兩條 3.5 GB 下載寫進同一組路徑,而把宣告提前到那把本來就在讀它的鎖裡,成本是零。

**3. 讀不到的 `frame-drop-count` 被當成 `0.0`。** 它是累計值,所以下一次取樣的差值變成整個計數器。實測(60fps 目標、0.33% 的健康掉幀率):

| | 值 |
|---|---|
| 乾淨取樣的穩態 | 0.33% |
| **一次讀取失敗之後的下一拍** | **9725%** |
| 0.35 平滑走回門檻以下 | 23 拍 = **6.9 秒** |

六點九秒的 UI 謊報卡頓,起因是一個逾時的屬性讀取。同一個檔案裡其他屬性都不是這樣處理的——`time-pos` 讀不到就整個樣本作廢,`vf` 另外帶一個 `vf_ok`,就是為了不讓「問不到」被寫成一個量測值。掉幀計數是唯一的例外。

**4. `restore_hwdec` 把被拒絕當成成功。** 它先 pop、先寫檔,再 `ipc.set`,而 set 失敗只是 `pass`。pop 在前是對的(成功時不能留過期紀錄),但 mpv 還活著、還在 copy-back 時,它原本的模式在記憶體和檔案裡都沒了:watcher 重試的 remove() 讀到空 map,下次啟動的 `_recover_stranded_hwdec` 也讀不到。一個逾時指令 = 那個播放器餘生都付 copy-back 的傳輸成本而身上沒有濾鏡。失敗就放回去;不必特別處理「真的走了」,`tick()` 本來就拿 `hwdec_pids()` 對掃看得到的行程。

**5. OSD 寫死 "TensorRT"。** 這是 §9.1 那輪 AMD 後端留下的漏網之魚,而且諷刺:這行字唯一會出現的錯誤場合,正是 ncnn 後端存在的理由。`backend_label()` 收在 `vs_script`,與 `.vpy` 檔頭、`app.js` 的 `backendName()` 三處同一措辭。

**方法論上值得記的一件事:** 第 1 項的後果,是讀了 `zz-fluid-ipc.lua` 才確定的——Python 這側完全看不出 `strip_stale` 沒有週期性 timer。跨語言的狀態機,不讀另一半就不算查過。

### 9.8 09-04:`mpv_ipc.py` 逐行讀完,一個 37 秒的批次讀取

`mpv_ipc.py`(243 行)是 §9.7 沒讀到的那個。逐行讀完只找到一個缺陷,但它不小。

**沒有答覆的 mpv,一次 `snapshot_playback` 要 37.6 秒。** mpv 用單一執行緒服務 IPC,所以「問不到」從來不是個別屬性的事實:一個停止回應的播放器(**正在編譯 TensorRT engine 就是最普通的到達方式**)十五個屬性一個都不答。而 `snapshot_playback` 的 `_get` 是逐一 `try/except IpcError`,每一次都把 `command()` 的 2.5 秒逾時走完。

實測(真的 `MpvIpc`,只把 handle 換成「收下寫入、永不回覆」;win32 分支 peek 到空就立刻回 `b""`,socket 分支 0.15 秒逾時後回 `b""`,兩條都會空轉到 deadline):

| | 修正前 | 修正後 |
|---|---|---|
| 單次 `get()` | 2.501 s | 2.507 s |
| `snapshot_playback()` | **37.647 s / 15 個指令** | **2.508 s / 1 個指令** |
| 回傳內容 | `vf_ok=False, media='', fps=''` | 完全相同 |

**關鍵在最後一列:那 37 秒買不到任何東西。** 每個欄位拿回來的都是第一次失敗後就已經定案的同一個預設值——跟 §9.3 `set_playing` 那條同一個形狀:**那些工作不可能改變任何結果**。而 `TICK_SECONDS` 是 0.3,`tick()` 又是逐一走播放器的,所以第二台播放器也一起等。

修法是**一份預算給整批,不是每次讀取各一份**:`snapshot_playback` / `rate_snapshot` 開頭算 deadline,`_get` 把剩餘時間當逾時傳下去,剩餘不足就直接回預設。預算取一個指令的逾時(`COMMAND_TIMEOUT = 2.5`)——一批讀取不該比它已經被允許花掉的那一次卡住的讀取更貴。會答的 mpv 完全不受影響:`rate_snapshot` 的 docstring 自己記著忙碌時全套約 230 ms,只有預算的十分之一。

`rate_snapshot` 是同一個缺陷的小號版本(3 次讀取 = 7.5 秒),但它是從 bridge 執行緒進來的,所以那筆錢是花在視窗上而不是背景 tick 上。一併改了。

**兩個實作細節值得記:**

1. **截止判斷不能寫 `remaining <= 0`。** `_command_locked` 的 deadline 用 `time.time()`,批次預算用 `time.monotonic()`,兩個時鐘的取整讓第一次逾時結束時剩餘值落在 0 的兩側各半——實測有一半的時候會放第二個註定失敗的指令上線。改成 `_MIN_READ = 0.005` 才是確定的。順帶:負的 `remaining` 傳進 `lock.acquire(timeout=)` 會直接 `ValueError`,所以那個下限也是正確性的一部分。
2. **`_FakeIpc.get()` 全部不吃 `timeout`。** 五個測試檔的假物件加起來 26 個測試立刻紅——這是好事,它證明那些測試真的走到 `ipc.get`。但也說明假物件與 `MpvIpc` 的介面沒有任何東西在對齊,改一個關鍵字就是這個規模。

**突變驗證(先跑不突變的對照組:238 passed):**

| 突變 | 結果 |
|---|---|
| 把 `_get` 還原成修正前的樣子(每次讀取各拿完整逾時) | **CAUGHT** —— 14 個指令、45.5 秒 |
| `SNAPSHOT_BUDGET = 0.0`(預算把會答的播放器也砍掉) | **CAUGHT** —— `vf` 沒被問到 |

第二個突變是刻意加的:**用預算換速度最容易的漏法,是連健康的播放器也少讀幾個屬性**——那會把「面板凍住」換成「面板空白」,是更糟的 bug。所以測試有一半在盯著這件事(`test_the_budget_does_not_cut_a_player_that_is_answering`,健康路徑必須讀滿 14 個;14 不是 15,因為 `filename` 只在 `media-title` 空的時候才問)。

事後 sha256 確認 `inject.py` 完全還原,全套 238 passed。

**順手改掉的一句過時文件:** FM 的 `CLAUDE.md` 寫著 `api.py`「currently has **no tests**;...nothing pins that the bridge keeps routing through it」。`tests/test_bridge.py` 有 6 個測試,第一個就叫 `test_settings_go_through_validation_not_straight_onto_the_dataclass`。用 `git merge-base --is-ancestor` 確認過寫 CLAUDE.md 的 commit 是加測試那個 commit 的祖先——寫的當下是對的,後來沒回頭改。

### 9.9 09-04:AX 三個模組讀完,零修改。一條假設撤回,一支量測工具作廢

挑檔的方式跟 §9.5 一樣:**先問哪些模組完全沒有測試**。`thumbnails.py`(96 行)和 `diagnostics.py`(79 行)是 AX 僅存的兩個,兩個都整份讀完;`player_widget.py`(504 行)只被一個測試檔碰到,也整份讀完。**三個都沒有找到站得住的缺陷**,這一節記的是查了什麼、以及兩件不該被重複的事。

**驗過是對的(不必再查):**

- `diagnostics.query_gpu()` 的五個欄位一次問完,任何一個不被支援就整批失敗、面板全空。實際跑過這台機器上的那條指令:`nvidia-smi --query-gpu=utilization.gpu,utilization.decoder,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits` → `0, 0, 9252, 16303, 38`,exit 0。**`utilization.decoder` 是有效欄位**,沒有這個問題。
- `thumbnails._grab_frame` 的暫存目錄帶 pid、`produced.replace(dest)` 同磁碟區所以是原子的、失敗不檢查 returncode 而是看有沒有產出檔案——三件都是對的,而且註解已經寫明為什麼。

**撤回一條假設:「修飾鍵先放開會讓按鍵卡在 mpv 裡」。**

`PlayerWidget` 的 mpv 按鍵名是**在事件當下**由 `event.modifiers()` 組出來的。按 Ctrl+1 → `keydown Ctrl+1`;先放開 Ctrl 再放開 1(很常見的順序)→ 放開事件已經沒有修飾鍵 → `keyup 1`。名字對不上,推論是 mpv 會一直以為 `Ctrl+1` 還按著。

拿真的 mpv 問過,不是用推的。把 `Ctrl+1` 綁成 `add volume 1`,答案就從判斷題變成計數器:

```
mpv v0.41.0-920-gdd5d17d32,input-ar-delay=200ms rate=40/s
  baseline                            volume=0.0
  +0.25s after keydown Ctrl+1         volume=4.0
  +1.25s, still held                  volume=45.0
  +1.0s after keyup 1 (mismatched)    volume=45.0     <-- 停了
  +0.6s after keyup Ctrl+1 (matching) volume=45.0
  控制組:成對的 keydown/keyup 相隔 0.05s  volume=1.0
```

**兩個事實。**(1)`keydown` 之後 mpv 會自己以 `input-ar-rate` 重複下去——1.25 秒 45 次,所以「按鍵卡住」如果真的發生,代價不是一次而是每秒 40 次。(2)**但名字對不上的 `keyup` 一樣把它放掉了**,而且沒有觸發 `1` 自己的綁定(不然會是 145 不是 45)。mpv 的 input 只記一個 last-key-down,`keyup` 放的是那一個,不管你報什麼名字。**所以這條假設不成立,`PlayerWidget` 現在的寫法是安全的。**

**一支量測工具作廢,記在這裡免得有人引用它的輸出。**

上面那條撤回之後,剩下的問題是:**按著鍵時焦點被搶走(Alt+Tab、通知視窗),Qt 還會不會送出 keyReleaseEvent?** 如果不會,依照事實(1)那就是每秒 40 次跑不停。

寫了一支探針想用真的 OS 輸入(`SendInput`)加真的焦點轉移來量。結果:

- 第一次 `GetForegroundWindow() != mine` 就 ABORT —— Windows 不讓沒收過輸入的行程搶前景。這一半是好的,守衛有作用。
- 加了 `AttachThreadInput` + `SetForegroundWindow` 之後視窗確實拿到前景(`isActiveWindow=True`、`hasFocus=True`),**但 `SendInput` 送的 `VK_F13` 連 keyPress 都沒有進到 widget** —— 事件清單是空的。

**所以「release delivered: False」這個輸出完全不能當證據** ——連對照組(按下去有沒有收到)都沒有成立,那一行只是在說「什麼都沒收到」。§5.2 的那句話又應驗一次:**測量工具本身會騙人**。懷疑是 `wVk` 帶 `wScan=0` 時 Qt 這條路徑收不到,但那也只是假設。

**這個問題因此仍然是開的,不要引用上面那支探針。** 要真的量,得換成有效掃描碼的按鍵,而那就會在焦點萬一跑掉時打進使用者正在用的視窗——所以下一次做之前先想清楚怎麼隔離(獨立桌面 / `CreateDesktop`,或者乾脆接受用合成事件只驗 `focusOutEvent` 這一半)。

**還有一條當場列出、當場查掉的:「工作管理員裡有兩個 `FluidMotion.exe`,`single.py` 是不是壞了」。** 沒有壞。單次 `Start-Process` 之後 `Win32_Process` 就是兩筆,而且 `ParentProcessId` 直接說明了關係:

```
ProcessId 14448  ParentProcessId 51008   <- 我的 shell
ProcessId 33828  ParentProcessId 14448   <- 上面那個的子行程
```

**PyInstaller onefile 本來就是兩個行程**:bootloader 解壓到暫存目錄之後把真正的程式當子行程跑,自己留著等它結束。應用程式實例只有一個。列在這裡是因為它看起來剛好像單一實例守衛失效,而那要花時間才查得清楚。

### 9.10 09-04:AX 兩個快取模組讀完零修改;FM 一個凍結的 lua,和一段量錯機制的註解

**AX 這半:`cache.py`(128)+ `contact_sheets.py`(391)整份讀完,沒有找到缺陷。** 兩個檔的每一條防護都已經有註解說明它防的是什麼,而且**現場也對得上**——直接去看這台機器上真正的快取:

```
thumbnails      103 檔  1.1 MiB  0 個目錄   (上限 500 MiB)
contact_sheets   93 檔  5.7 MiB  0 個目錄
```

沒有殘留的 `.tmp-*` / `.compose-*` 目錄、沒有 `.part-` 半成品、沒有舊格線的 `_12.jpg`。三種清理路徑都真的在跑。另外照 §5.4 確認過 `_PruneCacheJob` 真的會執行(`app.py:300`,建構時丟進 thumb pool),不是只寫在那裡。

已知且**不重列**:`probe_duration` 沒有快取(§7「查過、判斷不值得動」第 1 條)。

---

**FM 這半,找到一個:播放器自己的設定目錄永遠拿不到更新後的 lua。**

`_ensure_player_scripts` 一看到 `zz-fluid-ipc.lua` 存在就 return,docstring 也明說「Only ever adds a missing file」。但 `start()` 對 `settings.mpv_root` 是**每次啟動無條件重寫**。兩條路徑的政策相反,而腳本不是靜態的——`git log` 顯示 v1.0.0 到 v1.4.5 之間改過六次。

實測重放(把 v1.0.0 的腳本放進一個設定目錄,呼叫真的 `_ensure_player_scripts`):

| | 字元數 |
|---|---|
| v1.0.0 的腳本 | **192** |
| 現在出貨的腳本 | **4742** |
| 跑完之後磁碟上的 | **192**,原封不動,`needs_restart` 也沒設 |

192 對 4742 不是微調,是幾乎整份。v1.0.0 那份沒有 seek hold-off、沒有 stale-filter 清理,也沒有 per-player 的 `seek_hold-<pid>` 檔(`d0b1e76`)——少了最後那個,**任何一台播放器 seek 都會把濾鏡從其他每一台上扯下來**。而面板照樣說那台播放器 ready。

**唯一保持最新的目錄,正好是 AX Player 不會用的那個。** AX 的 config dir 是它自己的 `mpv-runtime`,不是 `C:\mpv`。

改成缺檔**或內容過時**都安裝,兩種情況都設 `needs_restart`(mpv 只在啟動時載入腳本)。

**比對必須比文字,不能比位元組。** `install_lua` 用 `write_text`,Windows 上把 `\n` 寫成 `\r\n`:磁碟上 4932 bytes,資源檔 4764 bytes,內容一模一樣。比位元組的話每次檢查都答「不同」→ 每個 session 重寫一次腳本,而且 `needs_restart` 永遠掛著,面板會一直要求使用者重啟一台腳本本來就正確的播放器。**這一半才是這個修法真正的風險,所以測試有一半在盯它。**

**動到一個既有斷言,說明理由。** `test_an_existing_script_is_left_alone` 斷言的就是舊行為。它寫的內容是 `"-- someone else's"`,看起來像在保護使用者手改的腳本——但 `start()` 早就對 `mpv_root` 那份無條件覆寫了,所以「不覆蓋使用者的修改」這個政策本來就不成立,只是不一致。改寫成兩個測試(過時要換 / 已最新不能重寫)。

**突變驗證(對照組 239 passed,3.10 與 3.14 都跑):**

| 突變 | 結果 |
|---|---|
| 規則換回 `is_file()` | **CAUGHT** —— 過時的腳本沒被換 |
| 比對換成 `read_bytes()` | **CAUGHT** —— 已最新的腳本被重寫 |

事後 sha256 確認 `watcher.py` / `bootstrap.py` 完全還原。

---

**順帶:修掉 `mpv_detect._embedded_player_pids` 一段機制寫錯的註解。**

它說「mpv 的 IPC listener 只綁一次,所以 zz-fluid-ipc.lua 後面的 rebind 是 no-op」。但 §7「知道就好」第 1 條和 `player_widget.py` 的註解都記著相反的機制(**mpv 會 rebind,後寫的贏**)。**同一件事在兩個 repo 有兩套互相矛盾的解釋**,而兩邊又都預測同一個結果,所以誰都沒發現。

實跑真的 `C:\mpv` 設定:

```
input-ipc-server = '%TEMP%/mpvSockets/11464'
F3 binding owner = 'zz_fluid_ipc'
新出現的管道     = ['%TEMP%\mpvSockets\11464']   (沒有 fluid-mpv-*)
```

**關鍵是 F3 的 owner。** 它證明 zz-fluid-ipc.lua 確實載入、也確實跑了 `set_property`,而活下來的值仍然是 mpvSockets 的 —— 所以絕不是「只綁一次、先寫的贏」。**後寫的贏,而 mpvSockets 是後寫的那個**:它在 `set_property` 前一行跑 `utils.subprocess({args={"cmd","/c","mkdir",...}})`,那會讓出 mpv 的事件迴圈,於是其他腳本(包括 `zz-`)全部在它等待期間載入並寫入,然後它才回來覆蓋。

**載入順序不等於寫入順序,只要有腳本會阻塞。** 「zz-」保證的是前者,而這段註解一直把它當成後者在推理。

方法論:這是 §5.6 那條的又一個實例——**觀測是對的(pipe 確實是 mpvSockets 的),接在上面的解釋是錯的**,而錯的解釋被寫進了程式碼註解。分辨兩個機制只花了一次 `input-bindings` 查詢。
