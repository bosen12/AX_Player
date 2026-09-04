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

### 9.11 09-04:`app.py` 逐行讀完,一個 v1.1.7 漏掉的 emit

`app.py`(1082 行)整份讀完。**只找到一個缺陷,但它是一整類問題裡唯一漏網的那個。**

**`GpuQueryJob` 是 `_thumb_pool` 上唯一沒走 `_emit_safely` 的 job。**

§7 記著「關閉時 emit 到已銷毀的 signals」是真的、已修(debug.log 有 12 筆)。`_ThumbJob`、`_SheetJob`、`_ScanJob` 三個都改用 `_emit_safely` 了,`GpuQueryJob` 沒有——它在 `diagnostics.py`,不在 `app.py`,所以那一輪掃 `ax_player` 的時候沒被歸進同一類。

找法不是猜的:把所有 `.emit(` 列出來,再扣掉走 `_emit_safely` 的和在 GUI 執行緒上的,剩下的**只有兩個**。`_MpvFetchWorker` 那個安全(signals 就是 QThread 自己,`loop.exec()` 等著它),另一個就是這條。

同樣狀態下並排實測(用 `shiboken6.delete` 明確銷毀 C++ 端,不去賭真實關閉的時序):

```
with the signals object destroyed under a running job:
  GpuQueryJob    RuntimeError out of run(): Signal source has been deleted
  _ThumbJob      run() returned normally
```

**可達性也量了。** `closeEvent` 的 `pool.clear()` 只丟得掉還沒開始的 job——註解自己寫著這件事——所以真正的暴露是「正在跑」的那段。`nvidia-smi` 在這台機器上 **47ms 中位數(7 次取樣、閒置)**,對上 1 秒的計時器,約是面板開著時間的 **5%**。不高,但代價是一個沒有人接的例外,而且視窗版沒有 console。

修法是一行,唯一要說明的是 import 位置:`app` 會 import `diagnostics`,所以相依不能反過來走模組層級,改成在 `run()` 裡 import——`app.py` 自己延後 import `player_widget` 和 `mpv_fetch` 是同一個理由。

新增 `tests/test_diagnostics.py`,這個模組**原本完全沒有測試**。四個測試,兩個盯這件事的兩半:

| 突變 | 結果 |
|---|---|
| 改回直接 `emit` | **CAUGHT** —— 關閉那個測試紅 |
| 守衛改成完全不 emit | **CAUGHT** —— 送達那個測試紅 |

第二個一樣是刻意加的:**守衛套錯地方會讓 GPU 那一列永遠空白,而那看起來就像一台沒有 nvidia-smi 的機器**,永遠不會有人回報。

**查過、沒有動的:**

1. `app.py` 其餘部分沒有找到缺陷。`open_folder` 的 `resolve()`、`play()` 的成員資格判斷、`_on_folder_scanned` 的過期掃描丟棄、`open_dropped` 的 `dnd.classify` 分流——每一條都有註解寫著它擋的是哪個曾經發生過的 bug,而且邏輯對得上。
2. **`_current` 播網址時被 `Path()` 壓壞**——§7「這一輪查過、故意沒做的」第 1 條,修了反而會壞 `set_sort_mode`。不重列。
3. **`nvidia-smi ~160ms` 這個註解的數字。** 我量到的是 47ms,差三倍。**沒有改它** ——我不知道原本那筆是在什麼條件下量的(播放中、RIFE 開著時 nvidia-smi 會爭用),而 §5.10 說推翻一個數字跟提出它一樣需要證據。兩個數字都留著:47ms 是閒置,原註解的 160ms 條件不明。反正結論不變,兩者都不該在 UI 執行緒上跑。

### 9.12 09-04:`ui.py` 讀完零修改;FM 一個在啟動途中被吃掉的「顯示」

**AX 這半:`ui.py`(1405 行,最後一個沒逐行讀過的大檔)整份讀完,沒有找到能站得住的缺陷。**

它的效能數字 §9.2 / §9.3 已經量完並接受(`set_items(3000)` 17.2ms、`_RowDelegate.paint` 0.037ms/列、`_apply_filter` 3-5ms、`set_playing` 已從 4.05ms 改回 0.92ms),**不要再列一次**。

**撤回一條假設:「暫停時診斷面板會變紅」。**

`DiagnosticsPanel._verdict_for` 完全沒有測試,而它拿 `estimated-vf-fps / container-fps`,低於 0.95 就印 DANGER 紅字「輸出幀率偏低」。暫停是使用者最常做的事,所以問題是:暫停之後 mpv 的 `estimated-vf-fps` 會不會衰減。

用 mpv 自己生一段 30fps 的 `testsrc` 片段,實跑:

```
playing        container=30.033371  estimated-vf-fps=30.030466  -> '正常播放 · 30.0 fps' ok=True
paused +1.0s   container=30.033371  estimated-vf-fps=30.030138  -> '正常播放 · 30.0 fps' ok=True
paused +2.0s   container=30.033371  estimated-vf-fps=30.030138  -> '正常播放 · 30.0 fps' ok=True
paused +5.0s   container=30.033371  estimated-vf-fps=30.030138  -> '正常播放 · 30.0 fps' ok=True
resumed        container=30.033371  estimated-vf-fps=30.010003  -> '正常播放 · 30.0 fps' ok=True
```

**mpv 暫停時保留最後一個值,八秒都沒動。假設不成立。**

順帶記一件**已知的近似**,不是缺陷:`_verdict_for` 的 1.8× 門檻假設補幀目標是兩倍。3x/4x 設定下只跑到 2.2× 會被判成「補幀運作中」。註解自己寫著「Fluid Motion's multiplier isn't exposed here」——要真的修得跨 app 傳倍率,不是 `ui.py` 的範圍。

---

**FM 這半,找到一個。挑檔法還是「哪些模組完全沒有測試」:`fluid_motion/app.py`(169 行)和 `icon.py`(30 行)是僅存的兩個。**

**第二份複本按下的「顯示」會在啟動途中被吃掉。**

`single.handover_or_continue` 把 `"show"` 寫進 hotkey 檔就結束自己,由執行中那一份把視窗叫出來。但兩端接線的時間差很多:`start()` 就把 hotkey 執行緒放出去了(50ms 輪詢),而 `app.main()` 要等 `import webview`、`create_window` 和 `tray_ok.wait(timeout=1.5)` 之後才呼叫 `set_on_show`。

`_consume_hotkey` 是**先 unlink 再 dispatch**,而 dispatch 寫成 `elif text == "show" and self._on_show:` —— 落在那段空窗的請求被讀走、刪掉、丟掉,**沒有任何東西會重試**。使用者點了圖示,視窗不會出現。

量了那個空窗:

```
engine.start() 回來(hotkey 執行緒開始輪詢)   t=0
engine.set_on_show() 被呼叫                    t=72 ms
```

**72ms 是下限,不是答案** —— 那次量測裡 `webview` 已經 import 過了(我為了 stub `webview.start` 先 import 了它),真實路徑還要付一次冷 import 和最多 1.5 秒的 tray 交握。這是這一輪的量測誤差,記下來免得有人引用 72ms 當成完整數字。

修法:接不到手的請求記在 `_pending_show`,`set_on_show` 接線時補送一次。**重點在第二半:只補送真的來過的請求。** 無條件在接線時叫出視窗會在每次啟動都彈窗,而那正是 `--start-hidden` 要避免的事,也是 autostart 的跑法。

新增 `tests/test_handover.py`。突變驗證(對照組 243 passed,3.10 與 3.14 都跑):

| 突變 | 結果 |
|---|---|
| 還原成會丟掉的 guard | **CAUGHT** —— 補送、以及只補送一次兩個測試紅 |
| 接線時無條件補送 | **CAUGHT** —— `--start-hidden` 那個測試紅 |

**查過、沒有動的:**

1. **`Engine._on_change` 是接不上的死線頭。** 每個 tick 後都會呼叫它(`if self._on_change:`),但 `start()` 唯一的呼叫端是 `app.py:31` 的 `engine.start()`,不帶參數,而且只有 `set_on_show` 沒有 `set_on_change`。UI 其實是每 900ms 輪詢 `get_state()`(`app.js:527`)。屬於 §7「查過、判斷不值得動」第 6 條的死碼類別,**照那條判斷不動**,列在這裡是因為它看起來像「UI 有推播」,會誤導讀的人。
2. **`tray_ok` 的兩個窄縫。** `tray_ok.set()` 在 `icon.run()` 之前,所以中間失敗會有一瞬間是「已設定但沒有圖示」;而 Explorer 重啟殺掉 tray 圖示之後 `tray_ok` 仍是 set,關視窗就變成沒有圖示的隱形行程。兩個都窄且不好驗證,沒有動。
3. **`single.try_acquire` 的 `ctypes` 用法是對的。** `restype = c_void_p`(避開 CLAUDE.md 那個 64-bit handle 截斷的陷阱)、`use_last_error` 加註解、`CloseHandle` 明確包 `c_void_p`、handle 存在模組全域所以不會被回收。`Local\` 命名空間對一個 per-user 托盤程式也是對的。

### 9.13 09-04:lua ↔ Python 的檔案協定。三件事查完,零修改

單檔已經全部逐行讀過,這一輪換方向:**跨檔案、跨語言的狀態機**。`zz-fluid-ipc.lua` 與 watcher 之間共用三個檔案(`alive`、`hotkey`、`seek_hold-<pid>`),逐條對過契約。**三件事都量了,沒有一件值得改。**

#### 1. 撤回:`0 <= hold_age` 不是生產環境的問題

`_seek_hold_age()` 是 `time.time() - st_mtime`,而 `interpolation_held_off` 要求 `0 <= hold_age < max_age`。負數 → 答「沒有 held」→ tick 會把濾鏡裝回正在進行的 seek 裡,正是這個檔案存在要擋的事。§5.12 把這個時鐘錯位記成**測試**偶爾失敗的原因並用 `os.utime` 修了測試——但沒有問「生產環境會不會也中」。

量了:

| 直譯器 | `time.time()` 解析度 | 剛寫完立刻讀,負數比例 | 最糟的「未來」幅度 |
|---|---|---|---|
| **3.10** | 15.625 ms | **869 / 6000(14.5%)** | **−0.0002 ms** |
| **3.14** | 0.0001 ms | **0 / 6000** | — |

**兩件事讓它不成立。**(1)幅度是 **200 奈秒**,不是毫秒——那是同一個 15.6ms 時鐘刻度內的捨入,不是真的時鐘偏差。(2)**3.14 上完全不發生**,而 `build.bat` 用 `py -3` 就是 3.14,**出貨的執行檔不受影響**;3.10 只是測試用直譯器。

再加上讀取時機:seek 進行中 `seeking` 為真,`interpolation_held_off` 走的是第一個分支、根本不看年齡;要中就得讓 tick 剛好落在最後一次 `touch_seek_hold()` 之後的同一個 15.6ms 刻度內、而且 `seeking` 已經清掉。

**§5.12 的結論是對的**,這裡只是補上「為什麼」——那個原因是直譯器的時鐘解析度,值得寫下來因為它會被重新推導一次。

#### 2. 查過、判斷不值得動:heartbeat 的 truncate race(§8.4 第 4 條的鏡像)

`_write_heartbeat` 是 `write_text`,不是原子寫入。lua 的 `fluid_alive()` 若剛好讀在 truncate 與寫入之間會拿到空字串,`tonumber` 回 nil → 判定 Fluid Motion 沒在跑。後果比 hotkey 那個方向重一點:`strip_stale()` 會**把濾鏡拆掉**、`begin_seek_hold()` 不會建立 hold(那次 seek 就慢)、F3 會說「請先開啟 Fluid Motion」。

量了寫入視窗(3000 次,已排除首次建立成本):

```
median 101us   p95 180us   max 5722us
1 秒寫一次 -> duty cycle 中位數 0.0101%
一次 lua 讀取大約 1/9,862 的機率落在裡面
```

**跟 §8.4 第 4 條同一個數量級、同一個判斷:不動。** 改成原子寫入(FM 的 `save_settings` 已經有那個模式)要為一個萬分之一、可自行恢復的事件,每天多做 86,400 次 rename,還多一個 `.tmp` 殘留的失敗模式。

#### 3. 第一次端到端驗證:AX 標題列那顆鈕真的會走到 Fluid Motion

四個元件、三種語言:

```
AXPlayerWindow.toggle_fluid_motion
  -> PlayerWidget._mpv_cmd("keypress", "F3")
    -> mpv input handler -> script-binding zz_fluid_ipc/fluid-toggle
      -> zz-fluid-ipc.lua toggle_fluid()
        -> 寫 "on" 進 %APPDATA%\FluidMotion\hotkey
          -> Engine._consume_hotkey
```

中間那一段最可疑:`keypress F3` 不是實體按鍵,而那是個 **script** binding 不是 input.conf 指令。`_ensure_player_scripts` 的註解記著曾經確認「那顆鈕是 silent no-op」的年代,但那是因為腳本根本不在 AX 的設定目錄裡;修好之後沒有人整條走過一次。

實跑(APPDATA 導到暫存目錄,否則會去切換使用者真的在跑的那一份;env 是**完整複製只換一個 key**,不是精簡 env——§1.1 為了精簡 env 花掉一整個版本):

```
connected on: \\.\pipe\fluid-mpv-32736
mpv says input-ipc-server = 'fluid-mpv-32736'   (命令列要的是 'axf3-49584')
F3 binding in AX's own mpv-runtime: ['zz_fluid_ipc']

沒有 alive heartbeat  -> hotkey 檔沒被寫  (正確,lua 應該拒絕)
有 alive heartbeat    -> hotkey 檔內容 'on'
```

**整條通。** 順帶又獨立證實了 §9.10 那個更正過的機制:AX 的 `mpv-runtime` 裡沒有 mpvSockets.lua,所以 zz-fluid-ipc.lua 的 `set_property` **贏過了命令列選項**——「後寫的贏」,而 `C:\mpv` 裡 mpvSockets 之所以贏只是因為它卡在 `utils.subprocess` 上、寫得更晚。

**這條不寫成測試**:它需要真的 mpv 子行程,而 FM 的測試守則是「用 `_FakeIpc`,不碰真 mpv、不需要 GPU」。記在這裡,附上重跑用的腳本形狀。

### 9.14 09-04:多行程共用狀態,以及一個活了六天的錯解釋

繼續跨邊界。這一輪查兩件事:**同時開三個 AX 行程時共用的持久狀態**,和**縮圖池上限的理由**。

#### 1. 驗過是安全的:`settings.ini` 沒有 resume.json 那個問題

§9.5 找到的資料遺失是這個形狀:每個行程把整份資料庫留在記憶體、整份寫回,最後寫的人蓋掉別人的(三個行程各存 400 部,丟失 792/1200)。`settings.py` 是它的姊妹儲存,被同樣那三個行程寫,也同樣是個模組全域。

差別應該是 QSettings 會 merge 而不是覆寫。**驗過,不是假設的** —— 因為那正是 `resume.py` 當初弄錯的假設。三個行程各自先讀、睡 0.6 秒重疊、再各寫一個不同的鍵:

```
[library]
last_folder=C:\\folder-A     (writer a) kept
sort=date                    (writer c) kept
recursive=true               (writer b) kept

survivors: 3 / 3
```

**QSettings 確實會合併,不動。**

#### 2. 修掉:三段註解還在引用 v1.1.5 已經推翻的解釋

`app.py` 有三處說縮圖池的上限是為了避免 `thumbfast: cannot create mpv subprocess`,原因是「同時太多 GPU 解碼工作階段」。

**§1.1 在 v1.1.5 就推翻了。** 真正的原因是 mpv `subprocess` 指令帶的 `env` 參數(帶 env 100% 失敗、不帶 0%);而 GPU 飽和那條是**直接測過的**——30 個 mpv 同時抓幀,thumbfast 式啟動 0/6 失敗。

`git blame` 的時間軸才是重點:

| 位置 | 寫入日期 | |
|---|---|---|
| `_SheetJob` docstring | 2026-08-24 | 早於根因 |
| `_thumb_pool` 註解 | 2026-08-24 | 早於根因 |
| 找到根因(`0699458`) | **2026-08-28** | |
| `request_thumbnail` docstring | **2026-09-04** | **晚了六天,又寫了一次** |

**這是 §5.6 在重演**:錯的解釋活得比觀測久,而且會擴散到**新**註解裡。README 一直是對的(第 268 行寫著 `CreateProcessW` 回 FALSE、err 87),只有程式碼註解沒跟上——跟 §9.10 那次 `mpv_detect` 的情況一模一樣,而且這次是同一份文件裡的自己人。

三處都改了。純註解修正、沒有行為變更,所以沒有新測試(同 §9.10 的處理)。

#### 3. 量了但沒有動:縮圖池的上限

上限的理由沒了,所以順手量它值不值得放寬。16 個合成的 1280x720 30fps 片段,清空快取後跑兩輪:

| 上限 | 16 次抓取 | 每次 | 失敗 |
|---|---|---|---|
| 4 | 3.13s / 2.73s | 195 / 171 ms | 0 |
| **8** | **2.38s / 1.96s** | 149 / 122 ms | 0 |

中位數 2.93s → 2.17s,**快 26%,零失敗**。

**沒有改成 8。** 兩個理由,都寫進註解了:

1. 那些片段 **170ms** 就解完,而 §7 量到真實一集約 **1.2 秒**。行程啟動在我的合成負載裡佔比高得多,所以這個加速幅度不能外推到真實檔案——真實檔案上更多並行等於更多同時進行的重解碼在搶同一張卡。
2. **整個 benchmark 期間沒有任何影片在播。** 而這個池的工作本來就是在使用者看片的時候跑的,那才是真正要緊的情況,而它完全沒被測到。

放寬上限是個真實的候選,但要用真實片源、而且要在播放中量。**在那之前維持 4。** —— **09-04 已補量並改掉,見 §9.15。**

### 9.15 09-04:縮圖池上限,補上 §9.14 缺的兩個變因

§9.14 自己把兩個缺陷寫下來了:片源是合成的 720p testsrc(170ms 就解完),而且**量的時候沒有任何影片在播**——那是這個上限唯一存在的情境。這一輪兩個都補上。

**片源**:12 個 1080p HEVC、8 Mbps、**GOP 250**。GOP 是關鍵——`--start=10%` 要從前一個關鍵影格解碼穿過來,所以真正的成本跟 GOP 長度和位元率走,不跟檔案長度走。單次抓取從合成片的 170ms 變成 **373ms**。

**負載**:整輪都有一支 1080p HEVC 在 `gpu-next` + `hwdec=auto-safe` 上播放,而且**讀它自己的掉幀計數**,不是只看抓取快不快。§9.14 量錯的就是這一邊:問題從來不是「縮圖跑多快」,而是「使用者正在看的那支影片會不會卡」。

| 上限 | 12 次抓取 | dropped | delayed | 播放推進 |
|---|---|---|---|---|
| (對照:不抓取) | — | 0 | 0 | 1.013× |
| 2 | 2.96s | **0** | **0** | 1.018–1.020× |
| 4 | 2.12s | **0** | **0** | 1.011–1.014× |
| **8** | **1.43s** | **0** | **0** | 1.027–1.049× |
| 12 | 1.24s | **0** | **0** | 1.008–1.050× |

**每一檔都是 0 掉幀、0 延遲影格。** 所以在這台機器上,這波抓取沒有讓被觀看的影片付出任何可量到的代價。**8 是曲線的膝點**:4→8 省 0.69s,8→12 只省 0.19s。

**改法,以及為什麼是「減半」而不是「調高」。** 舊公式 `min(max(cpu_count, 2), 4)` 在任何四核以上的機器都算出 4 —— 它既沒有用到大機器,也沒有保護小機器。新的是 `min(max(cpu_count // 2, 2), 8)`:

| cpu_count | 舊 | 新 |
|---|---|---|
| 4 | 4 | **2** |
| 8 | 4 | 4 |
| 16 / 24 / 128 | 4 | **8** |

**八核以下一律比舊值低,十核以上才超過。** 理由是量測只有一台、而且是強機(24 邏輯核心、RTX 5070 Ti):**四核筆電配內顯正是這裡量不到的那一台**,所以在沒把握的那一端要往下,不是往上。上限釘 8 而不是「一個檔一個行程」也是同一個理由——12 在這台沒事,不代表在別台沒事,而且它只值 0.19 秒。

公式抽成 `_thumb_pool_size()` 才測得到。三個測試分別釘住下界(`cpu_count` 是 None / 1 / 0 都不能掉到單執行緒)、上界、以及「小機器要比以前少」。三個突變都 **CAUGHT**:還原舊公式、拿掉下界、拿掉上界。

**方法論**:§9.14 的教訓在這一輪又應驗一次——**量錯邊比不量更容易讓人放心**。第一次量出「快 26%」,那個數字是對的,但它回答的不是決定這件事的問題。要看的是被保護的那一方,而那需要去讀播放中 mpv 的 `frame-drop-count`。

### 9.16 09-04:回頭驗上一輪改的東西,對的是**重**的那個消費者

§9.15 把池上限從 4 放寬到 8,但量的是**縮圖**——一個行程、373ms。**contact sheet 共用同一個池而且重得多**:§3.4 記著單張 sheet 抓幀 1.16s,外加一個獨立的 `probe_duration` 行程,而開資料夾一次排 `EAGER_SHEET_LIMIT = 12` 張。

**也就是說上限是在輕的消費者身上放寬的,從來沒有對重的那個驗過。** 這一輪補驗,方法完全相同:真實 1080p HEVC、真的 gpu-next 播放迴圈、讀那支播放器自己的掉幀計數。

| 階段 | 牆鐘 | 每張 | dropped | delayed | 播放推進 | 失敗 |
|---|---|---|---|---|---|---|
| 對照:不產生 | 4.00s | — | 0 | 0 | 1.010× | 0 |
| 上限 4 | 4.77s / 4.99s | 397 / 416 ms | **0** | **0** | 1.010–1.014× | 0 |
| **上限 8** | **4.19s / 4.29s** | 349 / 358 ms | **0** | **0** | 1.004–1.010× | 0 |

**沒有退步。** 重的消費者在上限 8 之下一樣是 0 掉幀、0 延遲影格,播放推進 1.004–1.014×。順帶快 13%(4.88s → 4.24s 中位數)。

**一個值得記的數字:sheet 的並行效率比縮圖差很多。** 單張約 1.5s(抓幀 1.16s + probe),12 張在 4 個工作緒下理論 4.5s、實測 4.88s(效率 92%);8 個工作緒下理論 2.25s、**實測 4.24s(效率 53%)**。所以 sheet 在大約 4–6 條就把某個資源吃滿了,這也解釋了為什麼放寬對它只值 13%,而對縮圖值 33%。**上限 8 對 sheet 幾乎是免費的,但也幾乎沒有用**——它的價值全在縮圖那一側。

#### `EAGER_SHEET_LIMIT = 12`:從「拍的」變成「量過的」

§7「查過、判斷不值得動」第 2 條說得很直白:**「`EAGER_SHEET_LIMIT = 12` 是拍的,不是量的。要調就調數字,不要改成『跟著捲動產生』」**。現在有數字了:

- 12 張 = **4.2 秒的背景工作,0 掉幀、0 延遲影格**。
- 每多一張約 350ms 的池時間、兩個 mpv 行程。

**沒有改。** 往下沒有壓力(4.2 秒的背景工作對播放是零成本);往上的收益只落在使用者實際捲到的列,而那些列本來就會在 350ms 的 hover 意圖延遲後即時產生。§7 那句警告仍然成立:要調就只調數字。

**這一輪沒有程式碼變更**,產出是把上一輪的改動對重負載驗過,以及把一個一直標著「拍的」的常數換成量過的。

#### 發了 v1.3.4,以及一個差點發錯的教訓

v1.3.3 以來累積的程式碼變更只有兩個:`a0c806e`(GPU 取樣的 emit 守護)和 `2789e44`(縮圖池上限)。兩個 build 都跑了(`build.bat` 自己釘 `py -3.14`),兩個資產都上去了。

**煙霧測試不是可選的。** 照 §5.4「修好之後要驗證它真的會執行」,發版前跑了一次 onefile:`debug.log` 出現 `mpv runtime: root=C:\mpv libmpv=True ... vapoursynth=True fluid_ipc_lua=True`,證明打包版真的啟動並走到 `main()`。(順帶:它選的是 `C:\mpv` 而不是內建 runtime,而那正是 `_log_mpv_runtime` 的 docstring 說要留意的事——這台機器上 `C:\mpv` 才是有 VapourSynth 的那個,所以選對了。)

**差點發錯的地方:** 等 onefile 建置完成時,第一個等待條件寫成「`dist/AXPlayer.exe` 存在就繼續」——它**立刻**就成立了,因為那裡躺著 **01:47 那次建置的舊檔**。差一點就把舊的二進位檔當成新版發出去。改成比對 mtime(比這一輪剛產生的 zip 新)才是對的。

**又是 §5.2 那條:測量/驗證的工具本身會騙人。** 「檔案存在」從來不等於「這一次產生的檔案存在」,而建置產物的目錄本來就會留著上一次的東西。以後等建置就比時間戳,不要比存在。

`C:\AX_Player` 的散布副本(`onedir/`、`onefile/`、`release/`)也一併更新,四個檔案逐一用 SHA256 對過。`release/FluidMotion.exe` 順手換成 v1.6.4。

### 9.17 09-04:FM 的網頁 UI —— 全部的 Python 讀完了,JS 還沒

前面幾輪把兩個 repo 的 **Python** 逐行讀完了,但 FM 的 `fluid_motion/ui/`(app.js 528 行)一直沒讀。而 CLAUDE.md 明說那裡是**安全邊界**,而且有真實的 XSS 前科(`media-title` 走 `innerHTML`)。

#### app.js 讀完:沒有找到缺陷

`innerHTML` 的 sink 只有三處 —— `renderPlayers`、`renderChecks`、`chipGroup`。把 36 個 `${...}` 插值洞全部列出來、逐一追回來源:

- `renderPlayers`:`p.label`/`p.name`/`p.media`/`p.missing`/`p.config_dir` **全部包了 `escapeHtml`**。其餘是 `p.width`/`p.height`(int)與布林/三元。
- `renderChecks`:`c.ok`、`c.label` 都escape 了。
- `chipGroup`:資料是 `PROFILES`/`MODELS`/`BACKENDS`/`SCENE_PRESETS`,**全是 JS 字面值**。
- **顯示卡名稱**(來自驅動程式登錄檔)走的是 `root.title = ...` 屬性指派,不是 `innerHTML` —— 原始碼註解已經寫明這是刻意的。
- `outLabel`、`target`、快取大小、GPU 讀數,全部走 `textContent`。

**邊界是守住的。**

#### 但守衛本身有一個缺口,而且量得出來

現有的守衛已經比它取代的「數 `innerHTML` 出現幾次」好很多 —— 它檢查每個插值洞裡有沒有 `escapeHtml`。**但欄位清單是手寫的十個名字**,而那是同一種過時、只是往上一層:**它對「有人記得的欄位」為真,對「實際存在的欄位」不是。**

實測那個缺口:

```
把 ${p.exe} 原封不動塞進 renderPlayers 的 innerHTML 樣板
-> 全套 243 個測試通過,包含兩個 XSS 守衛
```

`p.exe` 是 psutil 從行程讀出來的執行檔路徑,而 `PlayerProcess` 有 **13 個字串欄位,清單只列了 5 個**(漏掉 `exe`、`title`、`pipe`、`fps`、`estimated_vfps`、`output_fps`、`target_fps`、`realtime_label`)。

改成從 `dataclasses.fields(PlayerProcess)` 取 `str` 型別的欄位。**只取 str** 是刻意的:int 和 bool 正是 `${p.width}`、`${p.connected ? ...}` 在插的東西,要求它們包 `escapeHtml` 只會變成雜訊而不是守衛。非 dataclass 來源的(`c.*`、`gpu.name`、`state.error`)維持手寫。

**另外加了一個自我檢查**:推導出來的清單裡如果沒有 `p.media` / `p.exe` 就直接失敗。那正是被取代的計數式守衛的失敗方式——**守衛還在跑,但已經什麼都沒蓋到**。`from __future__ import annotations` 讓 `f.type` 是字串 `"str"`,哪天改成 `str | None` 或加了 `typing` 註記,這個推導就會靜靜地回傳空 tuple。

**突變驗證(對照組 243 passed,3.10 與 3.14 都跑):**

| 突變 | 結果 |
|---|---|
| `${p.exe}` 原樣 | **CAUGHT**(改之前是綠的) |
| `${p.title}` 原樣 | **CAUGHT**(改之前是綠的) |
| `${escapeHtml(p.pipe)}` | 仍然綠 —— 守衛不是一律禁止插新欄位 |
| 推導改成永遠取不到欄位 | **CAUGHT**(自我檢查生效) |

第三個突變是刻意加的:**一個會把正確寫法也擋下來的守衛,下一個人就會把它拿掉。**

事後 sha256 確認 `app.js` 完全還原,commit 只動到測試檔。

**方法論**:這是 §5 那組教訓的一個新變體。這個守衛前後三代,每一代都在修上一代「斷言了一個當時為真、但不會跟著程式碼走的東西」——先是數 sink 的個數,再是列欄位的名字。**能從程式碼推導出來的,就不要寫在測試裡。**

### 9.18 09-04:vendored patch 終於有測試了;以及公開頁面上的兩件事

這一輪查兩個一直沒碰過的表面:**vendored 的 `thumbfast.lua`**,和 **`docs/`(發佈出去的 GitHub Pages 站)**。

#### 1. `thumbfast.lua` 的三處手改,現在釘住了

CLAUDE.md 把它列為維護陷阱:「更新 thumbfast 要重新套用三處手改,而且 `mpv-runtime/scripts/` 和 `C:\mpv\scripts\` 兩份都要改」。先確認現況——**兩份位元組相同,八個 `-- AX Player patch:` 標記都在**,`subprocess()` 的四個呼叫點都沒有 `env`。不變式成立。

**但沒有任何測試釘住它。** 從上游直接覆蓋一份回來,§1.1 花一整個版本才找到的 bug 就回來了,而測試全綠。那個 patch 自己的註解裡就有 A/B:

```
8x without env, back to back      ........   (. spawned, X refused)
8x with env,    back to back      XXXXXXXX
8x with env,    0.5s apart        ........
```

新增 `tests/test_vendored_scripts.py`,三條:`subprocess()` 主體不能有 `env`、三處 patch 標記都在、**讀到的必須是這個 repo 的那一份**。

**第三條不是形式,而且它是這一輪最值得記的一條。** 這台機器上 `C:\mpv\scripts\thumbfast.lua` 與 repo 的那份**位元組相同**,所以讀錯檔案會讓前兩條照樣通過、什麼都沒證明——正是 v1.1.8 那個 `build.bat` 測試的失敗方式。錨點走 `bundled_mpv_root()`(`Path(paths.__file__)` 推出來的),不是 cwd,也**不是 `default_mpv_root()`**。

| 突變 | 結果 |
|---|---|
| 把 `env` 加回 subprocess 命令 | **CAUGHT** |
| 改掉一處 patch 標記 | **CAUGHT** |
| 錨點硬寫成 `C:\mpv` | **CAUGHT**,而且兩條內容測試**仍然是綠的** |

**一個失敗的突變也記下來。** 我第一次試的是「把錨點換成 `default_mpv_root()`」——結果三條全綠,我差點當成守衛無效。實際查了才發現:在原始碼 checkout 裡 `default_mpv_root()` 和 `bundled_mpv_root()` **是同一個路徑**(`C:\projects\AX_Player\mpv-runtime`),所以那根本不是一個突變,是個 no-op。§7 那條「突變測試自己也會騙人」的又一例:**突變沒改到東西,看起來就跟守衛失效一模一樣。**

#### 2. 公開頁面第四處,§9.14 那個錯解釋

`docs/index.html:167` 寫著:

> 一幀、一個 mpv 行程。**同時最多跑四個,因為 GPU 解碼工作階段是有限資源。**

**兩個錯**:前半在 §9.15 之後不再成立(現在是跟著核心數走的 2 到 8),後半正是 §1.1 推翻掉的那個解釋。§9.14 修了 `app.py` 的三處註解,**漏了公開頁面這第四處**——而這是使用者真的會讀到的那一個。已換成量過的數字。

**§5.6 又一次:錯的解釋會擴散,而且擴散得比修正快。** 下次再修這類東西,搜尋範圍要含 `docs/` 和 `README.md`,不要只搜 `*.py`。

#### 3. 沒有動,因為那是你的決定:公開頁面說 MIT,repo 是 GPLv2+

查 `docs/` 的時候撞到的,和上面兩件事無關:

| 來源 | 說什麼 |
|---|---|
| `LICENSE` | **GNU GPL v2** 全文 |
| `README.md:7` | GPLv2+ 徽章 |
| `README.md:79` | 「**GPLv2+** — see `LICENSE`」 |
| `CLAUDE.md` | 「GPLv2+, because libmpv is loaded in-process」 |
| **`docs/index.html` 第 7、60、235、238 行** | **「MIT 授權」** ×4 |

第 60 行是首頁最顯眼的那行副標(「Windows 10/11 · MIT 授權」),第 7 行是 meta description(搜尋結果會顯示的那段)。所以**對外的頁面說原始碼是 MIT,而 repo 裡放的是 GPL v2 全文**。

`README.md:214` 的「授權注意事項」看得出來為什麼會這樣:那一段是在**還沒決定**要用什麼授權釋出的時候寫的(「在決定要把 AX Player 用什麼授權釋出之前請先看過」),而 `LICENSE` 和徽章後來定案成 GPLv2+,頁面沒跟上。

**CLAUDE.md 明說「don't change the license casually」,所以我沒有動它。** 這是 §8.5 那一類——擁有者拍板的事。要改的方向大概是把頁面四處改成 GPLv2+ 對齊 `LICENSE`,但那是授權聲明,不是我該自己決定的。

### 9.19 09-04:照 §9.18 的教訓,把公開表面整個掃一遍

§9.18 結尾寫著「下次修這類東西,搜尋範圍要含 `docs/` 和 `README.md`」。這一輪就是那件事,對象是**兩個專案的 README 與發佈站**,把上面每個可查證的說法對回程式碼與 HANDOFF。

#### 對得上、不必再查的

- **FM 站上的補幀能力表**(`docs/index.html` 128–142 行)與 §3.1 **逐格相同** —— 2×/3×/4×/5×/6×/7× 的目標幀率、掉幀率、結論都一致。沒有漂移。
- **FM 的授權四處一致**:`LICENSE`(MIT)、README 徽章、README 兩節、站上頁尾,全部說 MIT。**跟 AX 的情況正好相反,而且是對的** —— FM 是走 IPC 的托盤程式,沒有把 libmpv 載進自己的行程,所以 MIT 站得住;AX 是 in-process 載入,所以 GPLv2+。兩個專案的授權**本來就該不同**,§9.18 那個問題是 AX 站上沒跟上它自己的 `LICENSE`。

#### 修掉:FM 的發佈站完全沒提 ncnn / AMD

`grep -c "ncnn\|AMD\|Radeon" docs/index.html` → **0**。一次都沒有,而那條路徑 **v1.6.0 就出貨了**。站上把「NVIDIA 顯示卡」列成硬需求,AMD 使用者讀完就走。

**這比一般的文件漂移更值得修**,因為 `log.py` 的 docstring 自己寫著那條路徑存在的理由:

> it exists because v1.6.0 shipped an AMD path nobody could test and asked users to report back; a report needs something to report

**要人回報,得先讓人知道它在。** 三處照 README 自己的措辭補上(需求清單、安裝步驟的下載量 3.5 GB vs 2.7 MB、第一次補幀的等待——ncnn 不編譯 engine 所以沒有那段),包含 ⚠️ 那段警語。**只講功能不講警語會比不講更糟**,所以測試把兩者綁在一起。

#### 順手撞到的:兩個站的離線版本號都是舊的

`docs/app.js` 會去 GitHub API 抓最新 tag 寫進 chip,HTML 裡那個數字是**抓不到時**(離線,或未驗證的 API 被限流——很容易)訪客看到的:

| | 站上寫的 | 實際最新 |
|---|---|---|
| Fluid Motion | v1.4.7 | **v1.6.4** |
| AX Player | v1.1.9 | **v1.3.4** |

**兩個都落後,所以這是有節奏的漂移,不是一次性的。** 兩邊都更新了,並且各自加了一道防線:

- FM:綁在 `__version__` 上(`test_public_surfaces.py`)。選它是因為**發版流程本來就要手動改 `__version__`**,這樣站上跟著一個已經存在的步驟走,不必多記一件事。
- AX:**沒有版本常數可以綁**,所以只在 `CLAUDE.md` 的 Releases 一節寫明要跟著 tag 一起改,並註明為什麼這邊沒有測試。

#### 新測試,以及它刻意不做的事

`tests/test_public_surfaces.py`:後端清單**從 `vs_script` 推導**(§9.17 的教訓:能推導的就不要手寫)、AMD 必須連警語一起出現、讀到的必須是這個 repo 的檔案(§9.18 的錨點教訓)、離線版本號等於 `__version__`。

| 突變 | 結果 |
|---|---|
| `docs/index.html` 還原成這一輪之前 | **CAUGHT**(兩條 docs 測試紅;README 兩條仍綠,因為 README 一直是對的) |
| 提到 ncnn 但拿掉 ⚠️ 警語 | **CAUGHT** |
| 版本 fallback 改回 v1.4.7 | **CAUGHT** |

**這一輪連續三輪都在同一條線上**:§9.17 說「能推導的不要手寫」,§9.18 說「錨點要指對檔案」,這一輪把兩條都用上,對象換成公開表面。三份公開文件的漂移都是同一個形狀 —— **沒有人會為文件跑測試,所以文件會比程式碼老。**

### 9.20 09-04:打包層 —— 出貨的東西對不對

最後一個沒讀過的表面:兩個 `.spec`、`packaging/`、`setup_mpv.py`、`mpv_fetch.py`。**spec 決定了什麼會出貨**,而在原始碼樹裡一切都在,所以少放一個資料檔只會在打包版壞掉。

#### 對得上、不必再查的

**兩個 spec 的 `datas` 都是完整的。** AX 的 `mpv-runtime/` 實際內容是 `LICENSES / NOTICE.md / fonts / input.conf / mpv.conf / script-opts / scripts / shaders` 加三個二進位檔(`mpv.exe`、`libmpv-2.dll`、`yt-dlp.exe`)。spec 列了前八項、刻意排除後三項(gitignore 也一致,由 `setup_mpv.py` / `mpv_fetch.py` 現抓)。**非二進位的部分 100% 覆蓋,沒有缺口。** FM 只有 `ui/` 和 `resources/` 兩個資產目錄,兩個都在。

**種子邏輯沒有清單漂移的風險。** `ensure_runtime()` 是 `for item in bundled_source.iterdir()` —— 整個目錄照抄,不是寫死的清單,所以 spec 加東西不會漏種。

#### 找到的:`yt-dlp` 會在「其他一切都正常」的安裝上缺席

`ensure_runtime()` 把三個二進位檔一起抓,但開頭是:

```python
if (default_mpv_root() / "libmpv-2.dll").is_file():
    return
```

**任何一個候選 root 已經有 libmpv-2.dll,就整段不跑。** 一台有自己 `C:\mpv` 的機器因此永遠不會執行到 `fetch_binaries`。那個安裝如果沒有自己的 `yt-dlp.exe`:

1. `ytdlp_exe()` → None
2. `player_widget` 的 `script_opts` 少掉 `ytdl_hook-ytdl_path`
3. mpv 的 ytdl_hook 退回找 PATH 上的裸 `yt-dlp`
4. 「開啟網址」對直連媒體檔正常,對需要解析的網址**靜靜失敗**

**這正是 `play_url` 的日誌當初為了什麼加的那種回報的形狀。** 它的註解寫著「every failure report for this feature turned out impossible to diagnose blind... every source-checkout reproduction attempt played back fine」——**而它在原始碼 checkout 下本來就重現不出來**,因為那裡的 `mpv-runtime/` 永遠有 `yt-dlp.exe`(`setup_mpv.py` 抓過了)。

**在這台機器上重現不出來。** 查過:`C:\mpv\yt-dlp.exe` **存在**(使用者手工組的那份剛好有),而 `yt-dlp` 不在 PATH 上。所以機制成立、路徑可達,但這台機器剛好躲過。

**沒有改行為。** 往別人的 `C:\mpv` 裡塞檔案不是這裡該做的事(可能唯讀,而且那是使用者自己的安裝),而把 yt-dlp 改抓進 `bundled_mpv_root()` 再加 fallback 是個真的修法,但那是一次網路下載的行為變更,建立在一個我重現不出來的假設上。**按 §5 的尺,這種時候該做的是讓它診斷得出來,不是猜著改。**

改的是:`_log_mpv_runtime()` 那一行補上 `ytdlp=` 欄位。那個函式的工作本來就是「記下哪個 root 贏了、它能做什麼」,而 yt-dlp 是清單裡唯一一個**在其他每項都是 True 的時候**會是 False 的能力——那個對比本身就是診斷。

新增 `tests/test_runtime_log.py`,三條,其中一條是推導式的(§9.17 的規矩):**`mpv_fetch` 抓的每一個二進位檔,都必須在這行日誌裡有對應欄位**。以後多抓一個而沒補欄位,就會在這個日誌唯一存在的情境裡靜靜地不被回報。

| 突變 | 結果 |
|---|---|
| 拿掉 `ytdlp=` 欄位 | **CAUGHT**(三條全紅) |
| 欄位寫死成 `True` | **CAUGHT**(只有第一條紅——證明它自己站得住,不是靠另外兩條) |

第二個突變是刻意加的:三條測試同時紅,分不出哪一條真的在測東西。

#### 留給你的一句話

如果日後有人回報「開啟網址不能用」,**先要 `debug.log` 的第一行**。`ytdlp=False` 加上 `libmpv=True mpv_exe=True`,就是上面這條路徑,而修法是往那個 root 放一個 `yt-dlp.exe`(或改成抓進 `bundled_mpv_root()` 並讓 `ytdlp_exe()` 也找那裡)。

### 9.21 09-04:所有表面都讀完了,所以這一輪查網子本身

前面幾輪把兩個 repo 的每個表面都讀過:Python、JS、Lua、CSS/HTML、spec、打包、docs、README、vendored patch。沒查過的只剩**測試本身**。

做法是一次**全常數突變掃描**:對每個模組層級的 `NAME = <字面值>` 做統一突變(數字換成明顯不同的值、字串加後綴),跑全套,記下誰活下來。

| | 抓到 | 活著 |
|---|---|---|
| AX Player | 3 | **37** |
| Fluid Motion | 12 | 27 |

比例差距跟測試數量一致(106 對 249)。大部分活著的本來就不值得釘 —— 顏色、內距、字體、廠商代號、釘死的上游版本、模型 id(沒有網路或沒有那張卡就判不了)。

#### AX:兩個真的有問題

1. **`resume.WATCHED_THRESHOLD = 0.95`** —— CLAUDE.md 特別交代「don't re-hardcode 0.95」,而「看完了」是兩個地方各自判的:`save_progress` 寫旗標、`ui.set_progress` 畫勾。任一邊自己寫死就會靜靜漂開,而唯一的症狀是勾勾跟清單篩選對不上。
2. **`thumbnails.THUMB_SEEK = "10%"`** —— §7 量過:固定抓第 3 秒會落在製作商 logo、黑畫面或 OP;百分比「依定義」在檔案範圍內,這才讓第二次的 frame-0 變成真正的例外路徑。退回絕對時間會把那個 bug 靜靜帶回來。

#### FM:三個關係,不是三個數字

`HOTKEY_POLL < TICK_SECONDS`、`HOUSEKEEPING_IDLE > HOUSEKEEPING_ACTIVE >= TICK_SECONDS`、`0 < REALTIME_SMOOTHING < 1`。三個都是有理由的決定,而**理由是關係不是數字**,所以釘得住又不擋合理的重新調校。

#### 五個測試共同的形狀,以及一個刪掉的

每一條都釘「決定產生的性質」而不是數字本身,並且**每一條都用「刻意的正常改動」反向驗證過**:門檻搬到 0.90、抓幀點搬到 15%、平滑係數 0.35→0.5,**全部仍然綠**。會把正確寫法也擋下來的守衛,下一個人就會把它拿掉。

**寫了又刪掉一個:`SNAPSHOT_BUDGET == COMMAND_TIMEOUT`。** 它**不可能失敗** —— `inject.py` 就是用 `COMMAND_TIMEOUT` 定義 `SNAPSHOT_BUDGET` 的,兩者依定義一起動,把 timeout 調成 12.5 那條斷言照樣綠。**不會失敗的測試比沒有測試更糟**,而這件事是靠突變才看出來的 —— 那正是跑突變的理由。理由留在那個檔案的註解裡。

#### 兩個關於工具本身的教訓

1. **字串突變對「有結構的字串」是無效的。** `FAINT = '#948373'` 加後綴變 `'#948373-MUT'` 活了下來,看起來像對比度測試沒用 —— 其實是 `luminance()` 只讀前六個字元,後綴根本沒進到計算裡。**換成真正的突變**(改回註解裡量過 3.43:1 的 `#7b6b5a`)就 **CAUGHT**。跟 §9.18 那次「錨點換成同一個路徑」一樣:**突變沒改到東西,看起來就跟守衛失效一模一樣。**
2. **掃描工具會順手改行尾。** 它用 `read_text`/`write_text` 還原檔案,於是把 `\n` 寫成 `\r\n`,掃完 `git status` 有五個檔案是「修改過」的。內容零差異(`git diff --ignore-cr-at-eol` 是空的),但看起來很像掃描弄壞了東西。**要還原就用 `git checkout`,不要相信「我寫回去了」。**

### 9.22 09-04:運算子突變掃描,以及它挖出來的一個真 bug

§9.21 掃的是常數,那只說得出「值沒有被釘住」,說不出那些值餵進去的**判斷**有沒有被測到。這一輪掃運算子:把每個 `>=`／`<`／`==`／`is`／`in` 逐一翻成鄰居,一次一個,重跑全套。

| | 抓到 | 活著 | 擊殺率 |
|---|---|---|---|
| AX Player | 17 | 26 | **40%** |
| Fluid Motion | **117** | 14 | **89%** |

**這個對照本身就是結論**,而且跟兩邊的測試數量一致(109 對 256)。

#### 找到一個真的 bug:「標記為未看」不會留下來

掃描指向 `resume.set_watched` 的提前返回,而寫測試去釘它的時候撞到更大的東西:**那個功能整個沒有效果。**

§9.5 為了多行程共存加了 `_merge_from_disk`——每個行程都把整份資料庫寫回去,所以寫入前要先把別的行程新增的條目 `setdefault` 回來。但那個合併是**在 `os.replace` 之前**讀檔案的,而檔案裡還有這次剛刪掉的那一筆,於是 `setdefault` 又把它放回去。

獨立重現(直接讀磁碟上的 JSON,不經過模組快取):

```
after save_progress      : ['ep1', 'ep2']   ep1 watched: True
after set_watched(False) : ['ep1', 'ep2']   ep1 still on disk: True
                                            and still says watched: True
in-memory cache says     : True
after a fresh load       : watched
```

**連記憶體快取都是錯的**,因為 `_merge_from_disk` 就地改的正是 `_cache` 本身。側欄那一列會清掉(走 `sidebar.set_watched`),所以**看起來有效**,直到重開資料夾或重啟——那是唯一看得見的地方,而那時候使用者早就不會把它跟剛才那個動作連在一起。

修法是把「這次刻意刪掉的鍵」一路傳到合併裡跳過。**刪除因此贏過另一個行程對同一個鍵的條目**,而 §9.5 的註解對一般情況選的是相反的;那個不對稱是刻意的——刪除是使用者剛剛指名要的。修完 `ep2`(另一筆)仍然保留,多行程合併沒有被弄壞(用「把合併整個拿掉」這個突變確認過)。

**這是 §9.5 那個修法自己帶進來的副作用**,而 §9.5 是這份文件裡最紮實的量測之一(792/1200 丟失)。**一個對的修法可以生出另一個 bug,而且那個 bug 會躲在原修法的正確性後面。**

#### 順帶補的三個分支

`_settled_frames` 的「大小跟上一輪一樣才算寫完」(v1.1.4 修的東西,一直沒有回歸測試)、`set_sort_mode` 的白名單、FM `_is_helper_mpv` 的兩個成員判斷。最後那個有實際後果:hover 預覽會生出第二個 mpv,把它當成播放器的話,watcher 會連上去、切 hwdec、對一個只解一張畫面就退出的行程加 RIFE 濾鏡——而 AX 的側欄每 hover 一列就產生一個。

#### 第三次撞到同一個形狀

`_is_helper_mpv` 那兩個突變第一次跑的時候「通過」了。原因是 shell 引號讓替換**根本沒套用上去**(原始碼用雙引號,樣式寫成單引號),而腳本沒有檢查。

**這是這個 loop 第三次撞到「突變沒改到東西,看起來就跟守衛失效一模一樣」**(§9.18 錨點、§9.21 hex 字串)。改成會先斷言「替換真的改到東西」再跑的腳本之後,兩個都是 CAUGHT。

**寫進方法論:突變測試的第一個斷言不是「測試紅了嗎」,是「我真的改到東西了嗎」。**

### 9.23 09-04:把 §9.22 留在 `contact_sheets.py` 的那一叢清掉

§9.22 的掃描在 `contact_sheets.py` 留下 18 個活著的突變,其中一整叢指向同一塊:**`--sstep` 抓不齊時的逐幀 fallback**。§7 說那是「the honest retry」,而它一行測試都沒有。

三個測試,對應三件事:

1. **快路徑短少就要走 fallback,而且會把每一幀都重抓一次。** `--sstep` 在 `GRAB_TIMEOUT` 時回傳已經寫完的部分,而 sheet 會用寫著九格的檔名快取起來、永不重看——所以接受八格等於**永久**快取八格。
2. **抓不到的那一幀不能讓後面每一格的時間標籤位移。** fallback 是把每一幀跟它自己的秒數配對,不是跟 `times` 依位置 zip;抓不到的那格直接不在清單裡,位置 i 就不再等於 `times[i]`。**這種錯誤是靜默的**:一部沒看過的片,contact sheet 怎麼標都像是對的。
3. 沒有 mpv 時三個進入點都不會生出任何行程。

| 突變 | 結果 |
|---|---|
| fallback 只留下失敗的 | **CAUGHT** |
| fallback 改成依位置 zip | **CAUGHT** |
| 短少的快路徑照單全收 | **CAUGHT** |
| 三個 `exe is None` 各自反過來 | **全部 CAUGHT** |

再掃一次同樣那幾個模組,§9.22 列出的這幾個突變已經死了:`settings.py:65` 的白名單、`cache.py:76` 的 `SCRATCH_MAX_AGE`、`contact_sheets.py:170` 的兩個(`size > 0` 與 `== size`)、`contact_sheets.py:318` 的 `one is not None`、`resume.py:85` 的 `data.pop(...) is None`。

#### 這一輪真正的教訓:**斷言錯了東西,守衛就等於沒釘**

第三個測試的第一版是錯的,而且錯得很有代表性:**只斷言回傳值,三個突變全部存活。**

```
SURVIVED  guard inverted in def probe_duration
SURVIVED  guard inverted in def _grab_frame_at
SURVIVED  guard inverted in def _grab_evenly_spaced
```

原因:`if exe is None: return None` 反過來之後,函式會繼續往下拿 `None` 去組命令列 → `str(None)` = `"None"` → 想執行一個叫 `None` 的程式 → `FileNotFoundError` → **既有的 `except OSError` 又把它變回 `None`**。從外面看,突變體和正確的程式回傳一模一樣的東西。

`guard` 真正的工作是「**不要生出行程**」,所以要斷言的是那件事。攔住 `subprocess.run` / `Popen` 並斷言零次呼叫之後,三個全部 CAUGHT。

**跟 §9.22 那條並列著看:**

- §9.22:突變沒套用上去 → 看起來像守衛失效。
- §9.23:守衛沒被斷言到 → 看起來像守衛有效。

**兩個方向都會騙人,而且都只有跑突變才看得出來。** 一個函式越是防禦性寫得好(`except OSError` 把每種失敗都收斂成同一個回傳值),它內部的分支就越難從回傳值上分辨——**這種函式要測的是它的副作用,不是它的答案。**

#### 剩下沒動的

`contact_sheets.py` 還有一些活著的突變,全部是同一類:`<=` 對 `<` 這種**只在剛好等於邊界時才不同**的翻轉,以及 `_grab_evenly_spaced` 內部要假的 `Popen` 才進得去的分支。前者收益低,後者要一整組行程假物件——列在這裡當作已知,不是漏掉。

### 9.24 09-04:第三種掃描,以及一個從來不可能失敗的 LRU 測試

§9.21 掃常數、§9.22 掃比較運算子。兩種都只碰得到「值看得見」的程式碼,而 §9.23 那一類——**只有副作用、從回傳值看不出來的守衛**——兩種都掃不到。

這一輪加第三種:**逐一把函式裡的每一個敘述刪掉**(換成 `pass`)再跑全套。四個模組(`cache` / `resume` / `thumbnails` / `dnd`):**117 個被抓到、35 個活著。**

#### 最重要的活體:`cache.py` 的 `entries.sort(key=atime)`

刪掉它,`test_prune_evicts_by_size_and_leaves_the_cache_under_the_cap` **照樣綠**。

原因很單純:那個測試把檔案照 `00.jpg`..`09.jpg` 建立,又讓 `00` 最舊——**目錄順序和存取順序一致**。所以「照 atime 排序後淘汰」和「照 scandir 給的順序淘汰」刪掉的是同樣那五個檔案。

**也就是說「最久沒被讀取的先淘汰」這件事,那個測試從來沒有測到過**——而那是 `cache.py` 整個模組的存在理由(docstring 第一句:「least-recently-*accessed* entries evicted first」)。

改法是讓兩個順序**對立**:先寫的那個給最新的 atime。照目錄順序淘汰現在會留下正好相反的一半。刪掉排序 → **CAUGHT**。

**這是 CLAUDE.md 開頭那條警告的第三個實例**(前兩個是 contact sheet 那個從沒呼叫過受測函式的測試、和讀到別的 repo 的 `build.bat` 測試)。三個的共同形狀:**測試的安排讓「對」和「錯」產生同一個結果。**

#### 另外兩個活體,都有真實前科

- **`get_progress` 的畸形條目守衛。** 至少有一台實機的 `resume.json` 裡有裸數字條目(某個更早的寫入路徑留下的)。側欄建清單時無條件 `entry.get()`,所以一筆壞的會在迴圈中間丟例外、**把它後面每一列都靜靜截掉**——資料夾只是看起來比較短。
- **`save_progress` 的 `duration<=0 or pos<0` 守衛。** mpv 對還沒解析出來的串流回報 duration 0,而五秒的輪詢照跑。少了它就是 Qt timer callback 裡的 `ZeroDivisionError`,**整個 session 的進度輪詢停在那裡**,而沒有別的東西會寫 `resume.json`。

三個突變全部 CAUGHT。

#### 剩下的 32 個活體:為什麼大多不值得動

絕大多數是**錯誤處理路徑**:`except OSError: pass`、失敗後的 `tmp.unlink`、`if not isinstance(...): return`。刪掉它們只有在「磁碟滿」「權限不足」「檔案在兩次 stat 之間消失」這類測試不會製造的情況下才看得出來。要測就得注入檔案系統錯誤,那是一整層假物件。

**列在這裡當作已知,並且記下判準:** 一個活著的敘述值不值得補測試,看的是**它防的那件事有沒有真的發生過**。這一輪動的三個都有紀錄——一台實機的壞 JSON、mpv 的 duration 0、以及 `cache.py` 自己的 docstring。其他的沒有。

#### 三種掃描合起來的樣子

| 掃描 | 找得到的東西 | 這個 loop 的產出 |
|---|---|---|
| 常數(§9.21) | 沒有被釘住的**值** | AX 2 個、FM 3 個決定 |
| 比較運算子(§9.22) | 沒有被分辨的**分支** | 一個真 bug(標記為未看)+ 4 個守衛 |
| 敘述刪除(§9.23–24) | 沒有被依賴的**副作用** | 一個不可能失敗的測試 + 2 個守衛 |

三種都跑完之後,**AX 的擊殺率從 40% 起步**,而 FM 一開始就是 89%——那個差距一直是這個 loop 最一致的訊號。

### 9.25 09-04:`settings.py` 幾乎整份可以刪掉;以及為了測得到而改的一次結構

敘述刪除掃描繼續:`paths` / `settings` / `diagnostics` / `debug_log`,**51 個被抓到、46 個活著**。

#### `settings.py`:除了 `set_sort_mode` 以外整份沒有覆蓋

每一個 getter 和 setter 都可以整個掏空而全套照樣綠。那是一堆使用者看得見的狀態:**啟動時重開的片庫**(`main()` 就靠 `last_folder()` 決定要不要落在檔案清單上)、視窗大小、三個開關。

新增 `tests/test_settings.py`,關鍵在於**透過重新開啟的 `QSettings` 驗證**,不是快取那一份——快取物件在什麼都沒寫進檔案的時候也會答對。

| | 之前 | 之後 |
|---|---|---|
| `settings.py` | 1 抓到 / 12 活著 | **18 抓到 / 1 活著** |

剩下那一個是 `flush()` 裡的 `_s().sync()`。**它在同一個行程裡分辨不出來**——QSettings 本來就會自己同步,所以那一行確實只是關閉時的雙保險。要分辨得開子行程(§9.19 那支腳本做過)。記在這裡,不硬補。

#### 為了測得到而改的結構:`mpv_root_candidates()`

`paths.py` 原本把候選清單寫在 `default_mpv_root()` 裡面。問題是:**清單在函式裡的時候,測試只能拿答案去比 `bundled_mpv_root()`,而那也正是 fallback 的回傳值**——所以把整個搜尋迴圈刪掉,斷言照樣成立。

```
SURVIVED  the candidate loop is skipped entirely
```

抽成 `mpv_root_candidates()` 之後(**FM 的 `paths.py` 一直都有同名的同一個東西**),兩件事分得開了:一個測試釘「bundled 有 libmpv 時它要贏」,另一個釘「bundled 沒有時要繼續往下走」。後者才是搜尋與 fallback 的分界。刪掉迴圈 → **CAUGHT**。

**哪個 root 贏不是裝飾**:§9.20 整節就是繞著它轉的——那決定 `yt-dlp.exe` 在不在(開啟網址能不能解析)、VapourSynth 在不在(Fluid Motion 的濾鏡能不能載)。

**這是這個 loop 第一次為了可測性動產品結構。** 判準是:那個決定有紀錄在案的後果,而且**除了改結構之外沒有辦法把它跟 fallback 分開**——不是「加個 seam 比較好測」而已。

#### 又寫了一個不可能失敗的測試,又刪掉

「什麼都沒有時 `default_mpv_root()` 仍然指向該安裝的位置」——`C:\mpv` 在這台機器上存在而且是寫死的候選,所以斷言必須接受兩種答案,**不管走哪個分支都會過**。理由留在原處的註解裡。

**連續三輪都出現這件事**(§9.23 斷言錯東西、§9.24 舊 LRU 測試、這一輪兩次)。它的共同前提很單純:**測試環境裡有一個我沒有控制的變數**——真實的 `C:\mpv`、真實的目錄順序、真實的例外處理。**把那個變數注入進來,才有辦法問出想問的問題。**

### 9.26 09-04:FM 的 `inject.py`,312 個敘述刪除全部被抓到

同一支掃描跑 FM 的 `inject.py`(803 行,濾鏡狀態機的核心):

```
caught 312, survived 0
```

**沒有一個敘述可以刪掉而測試不紅。** 這是這個 loop 跑過的所有掃描裡唯一一個滿分。

#### 三種掃描、兩個專案,合起來的數字

| 掃描 | AX Player | Fluid Motion |
|---|---|---|
| 常數 | 3 / 40 抓到(**7.5%**) | 12 / 39(31%) |
| 比較運算子 | 17 / 43(**40%**) | 117 / 131(**89%**) |
| 敘述刪除 | 117/152 與 51/97(53–77%) | `inject.py` **312/312(100%)** |

**這個差距在三種互相獨立的掃描下都成立**,所以它不是某一種掃描的偏誤。要投入測試工作的話,數字說的是 AX 那邊,而且說得很一致。

#### 但這個數字不能讀成「`inject.py` 沒有 bug」

**§9.7 就是逐行讀這個檔案找出五個缺陷的**,而那時候的測試同樣是綠的。

敘述刪除量的是「**測試會不會發現程式碼消失了**」,不是「**程式碼寫得對不對**」。§9.7 那五個裡:

- `restore_hwdec` 把被拒絕當成成功——那是 `except: pass` **寫在那裡**,不是少寫了什麼。刪掉任何一行都會紅,但那一行本來就是錯的。
- 讀不到的 `frame-drop-count` 被當成 `0.0`——同樣是「有一行,而且那一行的語意錯了」。

**兩種方法互補,不能互相取代:掃描找得到「沒有人依賴的程式碼」,逐行閱讀找得到「有人依賴、但依賴了錯的東西」。** 這個 loop 前半用的是後者,後半用的是前者,而兩邊都各自找到過真正的 bug。

### 9.27 09-04:`ui.py` 的 20%,以及怎麼讀這個數字

敘述刪除掃描跑 `ui.py`:**134 個抓到、520 個活著(20%)**,兩個 repo 裡最低的。

**這個數字要打折讀,而且折得很多。** `ui.py` 大半是繪圖程式碼——`_RowDelegate.paint`、`_draw_clamped_text`、`Sidebar.paintEvent` 的那排齒孔。刪掉一行 `painter.setBrush(dot)` 本來就不會有東西紅,除非去比對像素,而**這個專案從來沒有那樣做過,也不該為此開始**:像素比對在字型、DPI、Qt 版本之間都會碎。

所以正確的讀法不是「ui.py 覆蓋率 20%」,是「**活體裡有幾條是真的行為**」。掃完之後把 520 條逐一看過,分成三類:

| 類別 | 大致比例 | 值不值得動 |
|---|---|---|
| 繪圖(painter.*、幾何計算、顏色) | 大多數 | **不動**,理由如上 |
| 視窗/元件建構(`setFixedWidth`、`addWidget`、樣式表) | 一部分 | 不動,壞了會在啟動時自己現形 |
| **行為**(篩選、選取、選單、資料角色) | **少數** | 這一輪動的就是這些 |

#### 找到的:「只看未看完」整個功能沒有測試

`_apply_filter` 的 `unwatched_only` 分支可以整個刪掉,全套照樣綠。那是列在功能清單上、也寫在發佈站上的東西。

原因不難理解:既有的篩選測試(`test_a_hidden_row_is_not_part_of_the_selection` 等)全部是**搜尋框**那一半。兩個條件寫在同一個迴圈裡,只測了一個——**同一個函式有覆蓋,不等於它的每個分支有覆蓋。**

一併補上的兩條:`set_watched` 結尾的 `_apply_filter()`(開著篩選標成已看完,那一列必須從清單上消失,而不是留著跟篩選條件互相矛盾),以及 `PROGRESS_ROLE = 0.0`(看完的那一集不該還留著續播進度條)。

#### 第二次為了可測性動結構:`claim_selection_for_menu()`

第三個測試原本把 `_show_row_menu` 那四行**複製進測試裡再對著複製品斷言**——那正是 CLAUDE.md 用 contact sheet 當例子警告的套套邏輯,而我寫的時候沒有立刻看出來。

抽成 `claim_selection_for_menu()`,理由跟當初抽出 `_menu_target` 和 `build_row_menu` **完全一樣**:那個方法剩下的部分結束在 `QMenu.exec`,而它沒辦法從 Python 蓋掉。`_show_row_menu` 現在是三個可測的部分加一行 `exec`。

#### 又一次:無效的突變看起來就像通過

四個突變裡有兩個第一次跑是無效的:

- `self._apply_filter()` 在 `set_items` 裡也有一份,`replace(..., 1)` 改到的是那一份 → **SURVIVED**,而我差點記成「這條沒有覆蓋」。
- `PROGRESS_ROLE` 那行是它所在 `if watched:` 區塊裡唯一的敘述,刪掉變成語法錯誤 → pytest 報 4 個 collection error。**不能 import 的檔案不是突變體**,那不叫 CAUGHT。

改成用前後文定位、以及把值改錯而不是刪行之後,四個都 CAUGHT。

**§9.22 那條規矩要再加一句**:突變測試的第一個斷言是「我真的改到東西了嗎」,第二個是「**我改到的是我以為的那個地方嗎**」,第三個才是「測試紅了嗎」。

### 9.28 09-04:發了 v1.3.5,以及一個比 mtime 更好的新鮮度檢查

v1.3.4 以來的三個程式碼變更:`2c83238`(標記為未看的修正,**使用者看得見的 bug**)、`7966441`(啟動記錄多一個 `ytdlp=`)、`3504628`(`mpv_root_candidates()` 抽出,行為不變)。

**發版時機是被掃描擋住的。** §9.27 那支掃描全程在改寫 `ax_player/ui.py`(每個突變寫進去、跑完再還原),那段期間建置會把突變過的原始碼打包進去。所以這一輪的順序是**先發版、再掃描**,而不是反過來。**記下來:掃描期間不要建置。**

#### 新鮮度:從比 mtime 進化到比行為

§9.19 記過差點發出舊二進位檔的事,當時的修法是「等 mtime 比這一輪的產物新」。這次多一層,而且更硬:

```
2026-09-04T08:00:42 mpv runtime: root=C:\mpv libmpv=True mpv_exe=True
                    ytdlp=True vapoursynth=True fluid_ipc_lua=True ...
```

`ytdlp=` 這個欄位是 §9.20 那一輪才加進 `_log_mpv_runtime()` 的。**它出現在煙霧測試的日誌裡,就證明打包進去的是新的程式碼**——不是靠檔案時間推論的,是那份二進位檔自己說的。

**這是可以一直用下去的模式**:每次發版的煙霧測試,去找一個「這一版才有」的可觀察行為。時間戳只說得出檔案什麼時候寫的,說不出裡面裝的是什麼。

發完之後 `C:\AX_Player` 的三個目錄(`onedir` / `onefile` / `release`)一併更新,四個檔案逐一 SHA256 對過。

### 9.29 09-04:`app.py` 掃完,AX 的三個大檔到此全部掃過一遍

**85 個抓到、341 個活著(20%)** ——跟 `ui.py` 一樣的比例,而且要用同一把尺打折:`app.py` 有兩百多行是 `AXPlayerWindow.__init__` 裡的元件建構與訊號接線,刪掉一行 `.connect()` 在測試裡不會有東西紅,因為**沒有東西去觸發那個訊號**。

從活體裡挑出真正是行為的那一塊:**`request_contact_sheet` 的三個分支,整個函式沒有任何測試**,而三個分支各自都有寫在註解裡的理由。

| 分支 | 註解說的理由 |
|---|---|
| 已經在磁碟上 | 重複 hover、eager 預產、上個 session 留下的都走這裡,**都必須是瞬間的** |
| 已經在產生中 | eager 掃描和真人的 hover 會搶同一個檔案,而每個工作是**兩個** mpv 子行程 |
| 優先權 | eager 用 `-1` 排隊,使用者真的在看的那一列要插隊到十二個他沒要求的前面 |

三個突變全部 CAUGHT。

#### 一個已知、沒有為它硬改結構的:`closeEvent`

它整段都活著——存設定、`hide()`、`processEvents`、清兩個 pool、`player.shutdown()`,而註解記著那個順序是量出來的(「Tearing mpv down takes ~0.5s here... so the window sat on screen, frozen, for that entire time」)。

**沒有測它,理由是具體的**:那個方法結尾是 `super().closeEvent(event)`,而零參數的 `super()` 需要 `self` 真的是 `AXPlayerWindow` 的實例——用假物件呼叫未繫結方法會直接 `TypeError`。要測就得構造真的視窗,那會 `import mpv` 並起一個 libmpv 實例。

**§9.25 和 §9.27 各為了可測性動過一次結構,這次沒有。** 差別在判準:那兩次是「除了改結構之外沒有別的辦法把兩件事分開」,而且那個決定有紀錄在案的後果;這次是「要測就得起一個真的播放器」,而收益是一個關閉順序——**成本不成比例**。判準不是「能不能抽」,是「抽了之後測到的東西值不值那個代價」。

#### AX 三個大檔的掃描結果並列

| 檔案 | 抓到 / 活著 | 活體的性質 |
|---|---|---|
| `cache`/`resume`/`thumbnails`/`dnd` | 117 / 35(77%) | 錯誤處理路徑為主 |
| `paths`/`settings`/`diagnostics`/`debug_log` | 51 / 46 → 補完後 settings 從 1/12 變 18/1 | 存取器,補得掉 |
| `ui.py` | 134 / 520(20%) | **大半是繪圖**,補不掉也不該補 |
| `app.py` | 85 / 341(20%) | **大半是元件建構與訊號接線**,同上 |

**兩個 20% 長得一樣,原因卻不同,而兩個原因都不是「測試寫得不夠」。** 這是這幾輪掃描下來最重要的一句:**一個低擊殺率要先問「活著的是什麼」,再問「要不要補」——直接拿去當覆蓋率指標會把力氣花在繪圖程式碼上。**

### 9.30 09-04:FM 的 `--color-faint` 達不到 WCAG AA

AX Player 有 `test_dimmed_text_stays_readable`,而當初寫那個測試就抓到一個真的失敗(`FAINT` 是 `#7b6b5a`,在 `PAPER_2` 上 3.43:1)。**Fluid Motion 的介面是同一個形狀——深色底、三層漸暗的文字——卻沒有對應的檢查。**

調色盤是 oklch,所以先做 OKLCH → OKLab → 線性 sRGB → sRGB 轉換,**並且先用「純白對純黑必須是 21.00:1」驗過轉換本身**才敢往下讀(不然整份可能是在錯的色彩空間裡回報舒服的數字):

| 前景 | paper | paper-2 | paper-3 |
|---|---|---|---|
| ink | 16.32 | 15.54 | 14.34 |
| muted | 7.48 | 7.13 | 6.58 |
| **faint** | **3.62** | **3.44** | **3.18** |
| accent | 10.16 | 9.67 | 8.92 |
| live | 9.86 | 9.39 | 8.66 |
| danger | 6.49 | 6.18 | 5.70 |

**三種底色全部低於 4.5:1**,而 `--color-faint` 正是 `.fps-block dt` 和 `.player-dir` 用的顏色,兩者都是 `--text-xs`(0.64rem,約 10px)——3:1 的大字例外完全不適用。AX 當初失敗的值是 3.43:1,**幾乎同一個數字**。

改成 **62%**(最差底色 4.81:1)。**不用 60%**:那裡只有 4.44,是「看起來夠了但其實還差一點」的值,而 AX 的調色盤註解記著它當初拒絕過同一種擦邊球。

`tests/test_contrast.py` 從 `tokens.css` 讀顏色算,不是釘死字面值。另外兩個測試守著這個檢查本身:轉換要先驗過,以及**每個受檢 token 都必須真的被解析到**(改名或改成非 oklch 就會靜靜掉出檢查範圍,而檢查會照樣通過)。

| 突變 | 結果 |
|---|---|
| faint 退回 52% | **CAUGHT** |
| faint 用 60%(擦邊) | **CAUGHT** |
| faint 用 61%(剛好過) | 仍然綠——**那是合法選擇,不是回歸** |
| muted 調暗 | **CAUGHT** |
| 底色調亮到 ink 也不過 | **CAUGHT**(8 個裡 6 個紅) |

### 9.31 09-04:掃描工具的兩個操作教訓

#### 掃描進行時,不要跑測試,也不要 commit -A

§9.28 記過「掃描期間不要建置」。這一輪發現**跑測試也一樣**:改 CSS 之後跑全套,紅了一個 `watcher` 的測試——那不是我改的東西,是 `watcher.py` 的掃描正在同一棵工作樹上改寫它。

更危險的是 commit:`git add -A` 會把**當下那個突變體**一起提交進去。這一輪改成只 stage 那兩個檔案。

**規矩:掃描是把工作樹當成暫存空間在用。那段期間工作樹不是你的。**

#### 一個突變讓測試「掛住」,把整個掃描弄死了

第一次跑 `watcher.py` 的掃描,四十分鐘後拿到的不是結果,是一個 traceback:某個突變讓 pytest 永遠不結束,而 `subprocess.run` 的 1800 秒 timeout 直接往外拋,**整輪掃描的結果一起沒了**。

`watcher.py` 有三條 daemon 執行緒和好幾個 `_stop.wait()` 迴圈,刪掉其中一個敘述會留下一個永遠不退出的等待——**這種突變體在概念上是被抓到了(測試沒有通過),但工具把它當成錯誤**。

改成:per-mutation timeout 降到 120 秒(全套實際只要 4.5 秒,25 倍餘裕),而且 `TimeoutExpired` **計為 CAUGHT** 而不是往外拋。

**值得記的一句:掛住不是存活。** 一個會讓測試套件掛住的變更,在 CI 上比一個紅燈更貴——它會燒掉整個 job 的時間預算。工具原本的寫法等於把「最糟的失敗模式」翻譯成「工具自己壞掉」。

**修好之後重跑,`watcher.py` 是 481 / 481 全抓到**,而且那個會掛住的突變體正確地被計為 CAUGHT(輸出裡有一行 `(suite hung -- counted as caught)`)。

### 9.32 09-04:FM 兩個核心大檔,793 個敘述,零存活

| 檔案 | 行數 | 敘述刪除 |
|---|---|---|
| `inject.py` | 803 | **312 / 312** |
| `watcher.py` | 1060 | **481 / 481** |

**七百九十三個敘述,沒有一個可以刪掉而測試不紅。** 這兩個檔案是 CLAUDE.md 說的「largest, most central」——濾鏡狀態機和 Engine 迴圈——也是 §9.7 逐行讀完的那兩個。

#### 這對照著 AX 看才有意義

| | 常數 | 比較運算子 | 敘述刪除 |
|---|---|---|---|
| **AX** 核心小檔 | 3/40(7.5%) | 17/43(40%) | 117/152(77%) |
| **AX** `ui.py`/`app.py` | — | — | 20%(**大半是繪圖與接線**) |
| **FM** 核心 | 12/39(31%) | 117/131(89%) | **793/793(100%)** |

三種互相獨立的掃描,同一個結論。**如果只能挑一件事做,數字說的是 AX 的測試,而不是任何一邊的程式碼。**

#### 但這仍然不代表 `watcher.py` 沒有 bug

跟 §9.26 記的同一件事,值得再說一次:**§9.7 就是逐行讀這兩個檔案找出五個缺陷的**,而那時候測試同樣是綠的、同樣是 100% 的擊殺率。

那五個裡沒有一個是「少寫了一行」,全部是「**有那一行,而那一行的語意是錯的**」——`stop()` 不是屏障、`restore_hwdec` 把被拒絕當成成功、讀不到的 `frame-drop-count` 當成 `0.0`。**敘述刪除永遠找不到這一類**,因為刪掉一行錯的程式碼一樣會讓測試紅。

**一句話收尾這幾輪的掃描:擊殺率量的是「測試盯得多緊」,不是「程式碼有多對」。兩者都要,而且要用不同的方法去拿。**

### 9.33 09-04:FM 剩下的模組——54%,而其中一個不是「測不了」

`vs_script` / `mpv_detect` / `runtime` / `gpu` / `config` / `api` / `single` / `log` / `engine_cache` / `mpv_ipc` 一起掃:**360 個抓到、308 個活著(54%)**。

跟 `inject.py` / `watcher.py` 的 100% 差很多,但活體的分布說明了原因:

| 模組 | 活體 | 是什麼 |
|---|---|---|
| `mpv_ipc.py` | 92 | **win32 具名管道路徑**——測試用的是 socket 形狀的假物件 |
| `mpv_detect.py` | 56 | psutil 行程列舉、`list_win_pipes` |
| `gpu.py` | 45 | 顯示卡驅動登錄檔 |
| `single.py` | 22 | `ctypes` 的 mutex |
| **`api.py`** | **23** | **純 Python,而且是唯一的對外表面** |

前四類跟 AX 的繪圖程式碼同一個判斷:**沒有真東西就測不了**,補不掉也不該硬補。

#### `api.py` 的 23 個是另一回事

它是 CLAUDE.md 點名的 security boundary,也是網頁介面唯一碰得到的表面——而活著的**正好是整個表面**:`set_enabled` / `set_profile` / `set_model` / `set_autostart` / `start_setup` / `hide` / `quit` / `open_engine_cache` 的方法主體,以及每一個 `return self.get_state()`。

`test_bridge.py` 的六個測試蓋的是 `set_backend` 的**驗證**和 `clear_engine_cache` 的**回報**——**沒有一個檢查那些方法有沒有真的到達 engine。**

**被掏空的 setter 是一個「會動但什麼都沒做」的控制項**:chip 翻過去,900ms 後的輪詢把舊值讀回來,唯一的症狀是一個切不住的開關。而 `hide` / `quit` 掏空的話,視窗的關閉鈕和托盤的「結束」都會變成沒有反應。

新增 `tests/test_bridge_routing.py`。八個方法逐一掏空,**全部 CAUGHT**。有副作用的兩個(寫 autostart、`os.startfile`)都攔下來,測試不會真的動到登錄檔或開資料夾。

#### 掃描到此結束,以及它留下的判斷方法

兩個 repo 的每個模組都掃過三種突變了。**最後一句總結不是數字,是分類法**:

> 一個活著的突變,先問它屬於哪一類——
> **(a) 沒有真東西就測不了**(繪圖、win32、登錄檔、行程列舉)→ 不動,記下來;
> **(b) 只在測試造不出的錯誤條件下才看得出來**(`except OSError: pass`)→ 看那件事有沒有真的發生過;
> **(c) 純邏輯、而且有使用者看得見的後果** → 補。
>
> 這幾輪動的每一個都是 (c),而 (a) 和 (b) 加起來是活體的絕大多數。**先分類再決定,不要看比例做事。**

### 9.34 09-04:照缺陷的「形狀」去找,而不是照檔案

§9.26 和 §9.32 記著掃描找不到的那一類:**「有那一行,而那一行的語意是錯的」**。§9.7 的五個缺陷全部是那一類,而它們有**可以搜尋的形狀**:

- 「讀不到被當成一個值」(`frame-drop-count` → `0.0`、`vf_is_fluid(None)` → `False`)
- 「被拒絕的指令被當成成功」(`restore_hwdec` 的 `ipc.set` 失敗只是 `pass`)

這一輪不掃,改成**照第二個形狀去搜**:把狀態改變的呼叫吞掉例外的地方一個個看過(`grep "except" -A2 | grep pass`)。

#### 找到的:移除失敗以前回報成成功

`_remove_from` 有完整的錯誤處理——記 log、設 `_error`、回 `False` 讓下一個 tick 重試。**但那段程式碼到不了**:`remove()` 裡每一個 `command` 都自己把 `IpcError` 吞掉了。

實測(會回答讀取、但拒絕每一個 `vf` 指令的假 mpv):

```
vf commands attempted : [('vf','remove','@fluid'), ('vf','remove','@fluid')]
filter still on graph  : [{'name':'vapoursynth','label':'fluid'}]
_remove_from returned  : True
engine._error          : ''
```

**代價不只是少一行 log。** 移除之後的每一件事都假設圖是乾淨的:`restore_hwdec` 把播放器帶離 copy-back,而 VapourSynth 讀不了 GPU 常駐的影格——**殘留的濾鏡加上還原掉的 hwdec,是一個餵不進東西的濾鏡。**

#### 修法刻意保守,而且刻意避開 §9.1 那個坑

**被拒絕不等於還在。** mpv 對已經不存在的 label 一樣會回錯誤,那是第二次 remove 的常態——把它當成失敗會讓 tick 對著一台已經乾淨的播放器永遠重試。所以只有在**真的看到它還在**的時候才回報。

**而讀不到 `vf` 也不算看到。** 那是 `snapshot_playback` 用 `vf_ok` 劃的同一條線;那種情況維持既有行為,不新增一種失敗模式。

健康路徑**不多花任何一次 round trip**(檢查只在 `refused` 時才跑)——`remove()` 在 seek 路徑上,lua 每次 seek 都會拆一次,所以那條路徑上多一次讀取是要一直付的。

| 突變 | 結果 |
|---|---|
| 整段檢查拿掉(這一輪之前的狀態) | **CAUGHT** |
| 只要被拒絕就回報,不去看 | **CAUGHT** |
| 讀不到 `vf` 也算成殘留 | **CAUGHT** |
| 沒有被拒絕也跑檢查 | **CAUGHT** |

#### 方法本身值得記下來

**掃描問的是「測試盯得多緊」,這一輪問的是「哪裡還有同一種錯」。** 後者不需要工具,需要的是一份缺陷形狀的清單——而 §9.7 已經把清單寫好了,只是沒有人拿它當搜尋條件用過。

**下一個可以照樣搜的形狀,§9.7 也列了:「讀不到被當成一個值」。** 搜法是在外部讀取上找 `or 0` / `or 0.0` / `or ""` / `or []` 的預設值,再問那個預設值和「真的是零」分不分得開。

### 9.35 09-04:照著上一節指的方向找,在下載器裡找到了

§9.34 指名的形狀:**「讀不到被當成一個值」**。兩個 repo 的預設值全部掃過一遍,大多數是無害的(字串名稱、只拿來顯示的寬高、有 `if total:` 守著的除法)。有一個不是。

**`mpv_fetch._download` 的完整性檢查是 `if expected and received != expected`**,而 `expected` 是 `int(resp.headers.get("Content-Length") or 0)`——**伺服器不回報長度,整個檢查就自己關掉了。**

那個檢查的 docstring 記著它擋的是什麼:「Demonstrated against a server declaring 5 MB and sending 1: no error, 1 MB landed」。它擋得住那個,擋不住沒有宣告長度的。

#### 用真的 socket 量,五種 framing

| | 回應 | 結果(修正前) |
|---|---|---|
| A | 宣告長度、body 送一半 | 既有檢查擋下 |
| B | chunked、串流中途切斷 | `http.client` 自己丟 `IncompleteRead` |
| **C** | **沒有長度也沒有 chunked** | **接受 5 MB 檔案的 1 MB 並改名上去** |
| D | 宣告長度、完整 | 正常完成 |
| E | chunked、正常結束 | 正常完成 |

C 那種 framing 的 body **在連線結束時結束**,所以「被切斷」和「正常收完」從回應本身分不出來。而 `fetch_binaries` 是「檔案存在就跳過」——**那個壞掉的二進位檔永遠不會再抓一次**。

#### 修法用規則,不用猜大小

**HTTP/1.1 規定兩種 framing 至少要有一種**,所以「兩種都沒有」只會發生在 1.0 伺服器或不合規的 1.1 上——不是 GitHub 或 SourceForge,而這三個 URL 都在那兩邊。

**拒絕而不是接受,是因為兩種錯不對稱**:誤拒是一則錯誤訊息加一次重試,誤收是一個永遠不會再抓的壞檔案。(用大小下限去猜會是另一種寫死的假設,而且對 17 MB 和 119 MB 兩種檔案都得挑一個數字。)

#### 又一個 fixture 對不上 docstring 的既有測試

原本有一個 `test_a_server_that_declares_nothing_is_not_second_guessed`,理由寫「chunked 回應沒有 Content-Length,所以檢查必須讓步」。

**對了一半,而錯的那一半正是關鍵。** 它的 fixture 設 `headers = {}`——**連 `Transfer-Encoding` 都沒有**——所以它模擬的根本不是 chunked,而是唯一沒有任何保護的那一種。chunked 本來就不需要那次讓步(`IncompleteRead` 就擋住了),讓步真正放行的是 C。

拆成兩個測試,理由寫在新的那個 docstring 裡。**這是這個 loop 第四次遇到「測試的安排跟它自己說的意圖不一樣」**(前三個:contact sheet 那個沒呼叫受測函式的、`build.bat` 讀錯 repo 的、LRU 那個目錄順序跟存取順序一致的)。

四個共同的形狀:**docstring 說的是意圖,fixture 決定的是實際測到什麼,而沒有人把兩者對照過。** 對照的方法就是突變——把 docstring 說要擋的東西真的做出來,看它會不會紅。

### 9.36 09-04:守衛測試隔離的東西,自己沒有守衛

兩個 repo 的 CLAUDE.md 都寫著同一件事:conftest 的重導向擋住的意外**已經發生過**(AX:「prunes and rewrites the real user's thumbnail cache」;FM:「a test's tmp_path ended up written into the live mpv_root, breaking the app until someone noticed」)。

AX 只有最鈍的那一半(`app_data_dir()` 看起來像不像暫存路徑)。**FM 什麼都沒有。**

而那個鈍檢查擋不住 conftest 自己花最多篇幅在防的東西:**快取**。三個模組全域(`debug_log._log_path`、`settings._store`、`resume._cache`)各自把路徑解析一次就留著,所以 conftest 逐一重設。**少一個重設、或多一個新的快取**,結果是先跑的那個測試替其餘一百多個釘死目錄——而路徑「看起來像暫存」照樣成立。

#### 兩邊各加一個 `tests/test_isolation.py`

問的是鈍檢查問不到的三件事:

1. **每個落在 `%APPDATA%` / `%LOCALAPPDATA%` 底下的路徑輔助函式,都必須跟著環境變數移動。** 這條是**自我校準**的:read-only 的位置(`ui_dir`、`project_root`、`lru_cache` 過的 mpv root)本來就不在那底下,規則自己把它們排除——**不必手寫「哪些該檢查」的名單**,而那正是 §9.17 說的那種會過時的東西。
2. 測試期間被填充的快取,必須落在這個測試自己的目錄裡。
3. (AX)conftest 是否仍然重設了套件裡**每一個**模組級快取——用 `ast` 從原始碼推導。

| 突變 | 結果 |
|---|---|
| 路徑輔助函式被 `lru_cache` 起來 | **CAUGHT** |
| conftest 少一個重設 | **CAUGHT**(靠第 3 條) |
| 重導向指到非暫存目錄 | **CAUGHT** |
| (FM)`config.json` 跑出重導向目錄 | **CAUGHT** |

#### 第 3 條是被突變逼出來的

第 2 條原本的 docstring 宣稱它涵蓋了 conftest 的重設。**它沒有。** 把 `debug_log._log_path` 的重設拿掉,它照樣綠——單獨跑那個測試時它本來就是第一個寫 log 的,快取本來就是空的。

**外洩只在同一個 session 跨測試時才看得見,而依賴執行順序的測試比它要補的洞更糟。** 所以 docstring 改成只宣稱它真的驗證的事(理由留在原處),另外加第 3 條從原始碼推導覆蓋率。

**這是第五次「docstring 說的和 fixture 做的不一樣」,而這次是我自己寫的**,在寫完後一分鐘內被突變抓到。§9.35 說對照的方法就是突變——這一輪是那句話用在自己身上。

#### 一個操作上的注意

整輪突變**沒有把 `APPDATA` / `LOCALAPPDATA` 指向真的目錄**:`roaming_dir`、`engine_cache_dir`、`thumbnail_cache_dir` 都會 `mkdir`,而 `_PruneCacheJob` 會在裡面刪東西,何況這台機器上 Fluid Motion 正在跑。鈍檢查那一條改用「真實形狀但無害」的 `build/` 底下暫用目錄驗證——**要測「保護失效會怎樣」,不必真的讓它失效。**

### 9.37 09-04:拿 §9.35 的方法去審既有的守衛

前面找到的五個「docstring 說 A、fixture 做 B」都是撞到的。這一輪把它變成**主動的審查**:對每一條側欄守衛,**把它 docstring 說它擋的東西真的做出來,看那一條測試會不會紅**——不是看有沒有東西紅。

九條逐一還原它們記載的修正:

| 結果 | 條數 |
|---|---|
| CAUGHT | 7 |
| 我的突變寫錯 | 1 |
| **真的有洞** | **1** |

#### 有洞的那條:守衛站在 bug 底下一層

`test_removing_one_row_keeps_every_other_rows_thumbnail` 的 docstring 說:「Removal used to rebuild the whole list, which dropped every loaded pixmap」。

而那個 rebuild 在 **`AXPlayerWindow.remove_from_playlist`**,它的註解到現在還寫著「Not set_items(): ...dropped every loaded thumbnail... See Sidebar.remove_rows」。**但測試呼叫的是 `sidebar.remove_rows()`,比 bug 低一層。**

實測:把 `set_items` 放回 `remove_from_playlist`,**133 個測試全綠**。

補了一條站在正確層級的:驅動視窗的方法,檢查註解承諾的三件事——縮圖、搜尋文字、選取狀態都要撐過一次移除。放回 `set_items` → **CAUGHT**。

**這是第六個實例,而它的形狀跟前五個都不同**:前五個是 fixture 沒有造出 docstring 說的條件;這一個的 fixture 是對的,**入口點選錯了層級**。修好的地方在上層,守衛卻裝在下層——兩者都正確,但中間那段沒有人看著。

#### 另一條 SURVIVED 是我的錯,一併記下

`test_right_clicking_blank_space_still_opens_nothing` **自己就把 `_pointer_is_over_rows` monkeypatch 掉了**,所以我去改那個函式當然沒有反應。它測的是「給定指標在 viewport 內時 `_menu_target` 的閘門」,而它確實測到了。**守衛沒問題,是突變無效。**

**這個 loop 第四次踩到「無效的突變看起來就像守衛失效」**(§9.18 錨點、§9.21 hex 字串、§9.27 改錯位置)。這次的新變體是:**測試自己 monkeypatch 掉的東西,不能拿來當突變目標。** 選突變點之前要先看測試把什麼換掉了。

#### 這個審查方法值得留著

它比掃描便宜(九條跑完不到十秒),而且問的是掃描問不到的問題:**掃描問「有沒有東西紅」,這個問「該紅的那一條有沒有紅」。** 一條被別人順手蓋住的守衛,在掃描裡是 CAUGHT,在這裡是 SURVIVED——而後者才是它自己該負的責任。

### 9.38 09-04:同一個審查跑 FM,§9.7-3 的守衛也站錯層

把 §9.1 和 §9.7 記載的修正逐一還原,看**那一條**測試會不會紅。七條裡:

| 結果 | 條數 | |
|---|---|---|
| CAUGHT | 4 | stop() 之後的心跳、`_bootstrapping` 提前宣告、被拒絕的 hwdec 還原要放回去、OSD 不能寫死 TensorRT |
| 我的突變無效 | 2 | 見下 |
| **真的有洞** | **1** | §9.7-3 的掉幀計數 |

#### 有洞的:9725% 那個假掉幀率,守衛只站在消費端

`test_drop_sampling.py` 的兩個測試是對的,但它們的 fixture **自己組 `info` dict**(`"drops": state["drops"] if readable else None`)——所以它們釘的是 `_update_realtime` 拿到 `None` 之後的行為。

**沒有東西釘 `snapshot_playback` 把讀不到的 `frame-drop-count` 變成 `None` 而不是 `0.0`。** 而那正是 §9.7-3 的修正本身。

實測:把 `else None` 改回 `else 0.0`,**288 個測試全綠**。

補了兩條站在生產端的:讀不到必須是 `None`,讀得到必須是數字(**一個把 `drops` 一律回 `None` 的生產端會通過前一條,同時讓掉幀率永遠量不出來**)。兩個突變都 CAUGHT。

**這是第二個「守衛站錯層」**(§9.37 是第一個)。兩個的形狀完全一樣:**測試把被測對象的輸入直接餵進去,於是產生那個輸入的那一段沒有人看著。** 用 fixture 手工組資料很方便,代價是把生產端排除在覆蓋範圍外——而 §9.7 那五個缺陷裡有三個就在生產端。

#### 兩條無效的突變,同一個原因

- **`vf_ok`**:`snapshot_playback` 現在有**兩個** `vf_ok = False`——round 1 的預算分支多加了一個——而 `replace(..., 1)` 改到的是預算那個。改對行號之後 CAUGHT,守衛沒問題。
- **`_PREV_HWDEC` 的 pid keying**:我加的 `or _PREV_HWDEC.pop(0, None)` 在沒有鍵 0 的時候根本是 no-op。

**同一個檔案裡有兩處長得一樣的程式碼時,`replace(..., 1)` 是個陷阱。** 這是第五次踩到無效突變(§9.18、§9.21、§9.27、§9.37、這裡),而**這一次的成因是我自己前面幾輪加的程式碼**——round 1 的預算分支讓 `vf_ok = False` 從一處變成兩處。

**規矩再補一句:改之前先數一數那個樣式在檔案裡出現幾次。**

### 9.39 09-04:照 §9.38 的類別去搜,最大的一個是 `Engine.state()`

§9.38 記下的可搜類別:**測試把被測對象的輸入直接餵進去,於是產生那個輸入的那一段沒有人看著。** 反過來問「哪些生產端沒有人看」,兩個 repo 裡最大的一個是 `Engine.state()`。

**它是跟網頁介面之間的全部契約** —— 每 900ms 被輪詢一次,沒有別的東西跨過那個邊界。它產生**十五個鍵**、`app.js` 讀其中**十二個**,而既有覆蓋只有兩處 `engine.state()["error"]`。

**Python 這側改個鍵名,面板就靜靜地空掉。** 沒有錯誤、沒有例外、沒有測試會紅——`undefined` 渲染出來就是一片空白,而那跟「還沒有東西可報」長得一模一樣。這是這個 loop 反覆遇到的同一種症狀:**失敗的樣子和正常的樣子一致。**

新增 `tests/test_state_contract.py`,名單**從 `app.js` 解析**出來(§9.17 的理由),分三層:

1. 頂層鍵
2. 巢狀鍵——`state.gpu.name`、`state.bootstrap.running`、`state.settings.profile` 各自來自不同的 `to_dict()`,**會各自漂移**
3. 一個遲鈍的下限:萬一 `app.js` 被改成什麼都不讀,前兩層會通過而契約已經沒了

| 突變 | 結果 |
|---|---|
| 頂層鍵改名 | **CAUGHT** |
| 頂層鍵刪掉 | **CAUGHT** |
| `gpu.to_dict()` 把巢狀鍵改名 | **CAUGHT** |
| `app.js` 不再讀任何 `state` 欄位 | **CAUGHT** |

#### 兩個關於突變本身的細節

- **第二個突變第一次 SURVIVED,是我選錯了 selector**:我刪掉 `engine_compiling` 卻只跑那條遲鈍的下限測試,而那條的清單裡本來就沒有它。**衍生的那條抓得到,我沒讓它跑。**
- **第三個第一次是改 dataclass 欄位名**,結果是 collection error 而不是斷言失敗——§9.24 說過「不能 import 的檔案不是突變體」。改成只在 `to_dict()` 出口換鍵名,才是我的斷言抓到的。

**兩個都是「突變看起來有結論、其實沒有」的變體,而且都是在我自己的新測試上發生的。** 到這一輪為止,無效突變已經出現六次,而它們的共同解法只有一個:**跑完之後回頭問「紅的是我以為的那一條嗎、而且是被斷言抓到的嗎」。**

### 9.40 09-04:AX 這邊的同一個邊界 —— 診斷面板

§9.39 對 FM 的 `Engine.state()` → `app.js` 做了契約檢查。AX 有一模一樣的形狀:**兩個生產端餵一個消費端**。

| | |
|---|---|
| 生產 | `PlayerWidget.diagnostics()`(mpv 在做什麼)、`diagnostics.query_gpu()`(顯示卡在做什麼) |
| 消費 | `ui.DiagnosticsPanel`,按名字從純 dict 裡讀 |
| 之間 | **什麼都沒有** |

任一端改個鍵名,那一列就顯示「—」——**而那正是「值真的取不到」時顯示的東西**。

**現況查過是對的**:面板讀 18 個欄位,兩個生產端合起來全部涵蓋。缺的是沒有東西在維持它。

新增 `tests/test_diagnostics_contract.py`,兩邊都用 `ast` / regex 從原始碼讀出來——所以這個測試**不需要 libmpv 也不需要 nvidia-smi**。(既有測試已經 import 過 `player_widget`,但沒必要為這件事多綁一個相依。)

五個突變全部 CAUGHT:改鍵名、刪鍵、`query_gpu()` 改鍵名、面板悄悄不再讀某欄位、抽取器找不到生產端。

#### 順帶記一個「不是錯誤」的發現

`display_fps` 每次刷新都從 mpv 讀出來、**從來沒有被顯示過**。

**一個生產端跑在消費端前面不是錯誤**,一秒一次 python-mpv 的屬性讀取也不值得為它動刀。所以第三個測試不是斷言它該消失,而是**把「產生了但沒人讀」的清單釘在那裡**:它現在是 `["display_fps"]`,變了就要有人解釋。這樣既不逼人清掉一個無害的東西,也不讓那份清單無聲無息地長大。

#### 這兩輪合起來是一個模式

§9.39 和 §9.40 找的是同一種東西:**跨語言/跨模組、用字串鍵連起來、而且兩邊都沒有型別檢查的邊界。** 兩個 repo 各有一個,兩個都只靠人記得。

**判斷一個邊界要不要這種守衛,問三個問題:**
1. 兩邊是用**字串**連起來的嗎(不是函式簽章)?
2. 一邊改了名字,另一邊會**安靜地**降級嗎(不是丟例外)?
3. 那個降級的樣子,跟**正常的空狀態**長得一樣嗎?

三個都是「是」,就值得從其中一邊推導出清單去釘另一邊。這兩個邊界三題全中。

### 9.41 09-04:第三個三題全中的邊界 —— 寫給 mpv 的屬性名稱

拿 §9.40 那三個問題去掃,還沒守衛的最大一個是**屬性名稱字串**:字串連起來、寫錯不會丟例外(`_prop` 全捕捉、`_get` 有 `IpcError` 守衛)、而降級的樣子跟「值真的取不到」一模一樣。

**而且它有前科**,就寫在 `inject.py` 裡:

> mpv's property is estimated-vf-fps. The name used here until now, estimated-vfps, does not exist, so `_get`'s IpcError guard swallowed the "property not found" reply and returned None every single time — the fps readout has been silently falling back to container-fps.

#### 先量:32 個名稱,0 個錯

兩個 repo 一共 32 個屬性名稱,拿去問一台真的 mpv(v0.41.0-920)。**全部存在。**

**關鍵在 mpv 自己分得出兩種答案**,這才讓這件事可查:

```
property not found    -> 名字寫錯了
property unavailable  -> 名字是對的,只是現在沒有值(什麼都沒播)
```

沒有這個區分,一個 idle 的 mpv 對「對的名字」和「錯的名字」都答不出值,就查不了。

#### AX 加守衛,FM 不加

**AX**:名稱用 `ast` 從 `player_widget.py` 抽出來(不是寫死清單),開一台 idle mpv 一次問完。`mpv.exe` 是 gitignore 的,所以沒有它就 `skip`。**實測整個檔案 0.4 秒**——比預期便宜,因為 `--no-config --idle --vo=null --ao=null` 的 mpv 起得很快。

突變:把 `hwdec_current` 打錯 → CAUGHT;另外加一個全新的假名稱 → CAUGHT(**只有第二條紅**,證明它自己站得住)。

**FM 不加**,理由是它的測試守則明寫「用 fakes,不碰真 mpv、不需要 GPU」。而硬塞一份手寫的名稱清單當絆線,正是 §9.17 說的那種會過時的東西——**一份只能靠人維護的清單,價值是「讓人停下來」,不是「證明是對的」**,而這裡已經有更好的東西:真的去問 mpv。

**FM 那 18 個名稱這一輪驗過了。** 重驗的方法:起一台 `--idle` 的 mpv,對每個名字送 `get_property`,看回的是 `property not found` 還是 `property unavailable`。

#### 一件差點漏掉的事

第一次跑那個新測試是「2 passed in 0.40s」,而**我不相信那個數字**——spawn 一台 mpv 再問 14 個屬性不該這麼快。所以先注入一個錯字去驗它有沒有真的在做事,結果是 CAUGHT,速度只是真的快。

**如果那時候直接相信綠燈,我就會留下一個可能什麼都沒做的測試。** 這跟 §9.39 的「紅的是我以為的那一條嗎」是同一條規矩的另一面:**綠得太快也要問一次。**

### 9.42 09-04:清掉掛著的兩件,發 AX v1.3.6 / FM v1.6.5

#### 一、網站對外說了十天的 MIT(§9.18 那件,終於處理)

之前一直當成「授權有爭議、留給 owner 決定」。**查了 git 才發現不是爭議,是漏更新。**

`b85e59d`「Release under GPLv2+」動的是 `LICENSE`、`README.md`、`NOTICE.md` —— **沒有碰 `docs/index.html`**。所以 8/25 之後,公開頁面在四個地方說原始碼是 MIT,包含搜尋引擎會引用的那段 `<meta>` 描述。

往 `LICENSE` 的方向對齊是保守方向,沒有放寬任何東西,所以這不是 CLAUDE.md 說的「不要隨手改授權」。Anime4K 的 MIT 留著 —— 那是別人的授權。

守衛不寫死授權名稱:**`LICENSE` 是法律真相 → README 徽章是這個專案給它的簡稱 → 網站對著徽章檢查**。之後真的改授權,改那兩個權威來源就會反過來要求網站跟上。範圍靠「授權」兩個字,專案講自己用它、列第三方鳴謝不用。

六個突變全 CAUGHT,含一個「把『授權』改寫成 licence」—— 防這個守衛自己變成空轉。

#### 二、fps 讀數有沒有真的問到 mpv,沒有人在守 ★

§9.41 說 FM 那 18 個名稱不加守衛,理由是「不碰真 mpv」。**那個理由對,但結論偷懶了。**

順著查 FM 的假 IPC,發現 `test_config_runtime.py` 有 **15 處把假 IPC 餵成 `estimated-vfps`** —— 正是那個不存在的名字。生產碼問的是 `estimated-vf-fps`,所以假的從來沒服務過真的那個名字。

先驗證再下結論:改名前後都 294 passed,**行為中立**,那些 key 是死的。沒有測試靠它們過。

但接著問了真正該問的一題:**把 `inject.py` 兩處改回錯名字(完整重現原始 bug),會不會有人紅?**

```
294 passed
```

**那個修正當初沒有配回歸測試。** 這正是 CLAUDE.md 寫的「每個修正都要有回歸測試」,而它自己漏了。

新守衛不比對字串 —— 比對字串會對「mpv 沒有的名字」也通過,那就是 bug 本身。改成讓假 IPC 給出**互相不同**的 container 與 decoder 速率:只有真的問到 mpv 答得出來的東西,才可能讀到第二個數字。**不用真 mpv,合 FM 的守則**:名字錯了從假的那一側就看得出來,因為沒人服務的名字讀起來就是「不存在」。

四個突變全 CAUGHT,兩個半修各自只紅它自己那一站,外加「拿掉退路」證明前兩條不是靠不退回過的。

**教訓**:§9.41 判斷「FM 加不了守衛」是對的 —— 但那只否定了*那一種*守衛。同一個缺陷還有別的角度可以釘,而我當時沒有再問一次。

#### 三、本來想加、查完不加的守衛

原本要讓假 IPC 拒絕「生產碼從來沒問過的屬性名」。用 ast 掃兩側之後:10 個被餵進去的名字裡有 4 個「沒人問」,而**四個都是誤報** —— `video-sync` / `hr-seek-framedrop` / `temporal-dither` 來自 `inject.py` 的 `PLAYBACK_PROPS` tuple 常數(不是 call 的參數),`window-minimized` 則是**故意永遠不碰**的,測試餵它就是為了證明沒被碰。

4/10 誤報的守衛要配一份例外清單,那就是 §9.17 那種會過時的手寫清單。**不做。**

順帶確認沒問題:`estimated_vfps`(底線)是內部 snapshot 的 key,`inject.py:445` 產生、`watcher.py` 與 `app.js:340` 消費,一路一致。名字取得不好(呼應了那個錯的 mpv 名字),但它是私有 key,接得是對的。

#### 四、這一輪自己踩的:cwd

**同一次 Bash 呼叫裡 `cd` 是持續的。** 兩次因此打錯目標:

1. 改 AX 的 `ver-chip` 時人還在 FM 目錄 —— sed 去 FM 的檔案裡找 `v1.3.5`,沒找到,靜靜地什麼都沒做,而我差點就當它成功了。
2. commit AX 時同樣在 FM,得到「nothing to commit」。

這跟 CLAUDE.md 記的那個「build.bat 測試讀 cwd 相對路徑、開到別的 repo 的檔案」是**完全同一種形狀**,只是搬到了 shell 上。**之後一律 `git -C <path>` 和絕對路徑。**

第一個之所以被抓到,是因為印出來的行號和內容不對(顯示的是 FM 的 chip)。**改完要印出來看,不要只看 exit code。**

#### 五、發布,以及差點漏掉的 zip

三個產物的時間戳都是新的 —— 但 `dist/AXPlayer-onedir.zip` **停在 01:48**。`build.bat` 不打包 zip,它是 release 資產,要另外從剛建好的 `dist/AXPlayer/` 重打。§9.28 那次是「等檔案存在而不是等它變新」,這次是「新建了 A,卻發了從舊 A 打的 B」。

發布前後的驗證鏈:

```
FM 新 exe 自己報 "Fluid Motion 1.6.5 start"   <- 比時間戳強:版本在 binary 裡
AX 新 exe 吐出 "ytdlp=" 那一行                 <- 只有新版有的行為
發行複本 6 個檔案 SHA256 逐一 MATCH
onedir 複本 359 檔 vs 359 檔,無殘留舊檔
把 GitHub 上的資產抓回來重 hash,3 個全 MATCH  <- 端到端,發出去的就是測過的
```

最後一條是這次新加的。前面每一步都可能對,而發出去的是別的東西。

### 9.43 09-04:第四個三題全中的邊界 —— JS 抓的 DOM id ★

拿 §9.40 那三題掃還沒碰過的接縫。查了 HANDOFF:`.spec` 的 `datas`、signal emit、`input.conf` 都掃過了,**`getElementById` 零命中**。

#### 先量,而且第一次量錯了

探針掃 `getElementById("...")`,結果:

```
AX docs : 8 ids, 8/8 found
FM ui   : 0 ids                    <- 21 KB 的 app.js
```

**21 KB 的檔案「0 個 id」不合理。** 照 §9.41 那條「綠得太快也要問一次」去挖,FM 用的是本地包裝:

```js
function $(id) { return document.getElementById(id); }
```

補上之後是 **30 個**。那個「0 unresolved」本來是空轉的。

補完的結果:AX 8/8、FM 30/30,全部對得上。**現況乾淨,缺的是沒有東西在維持它。**

#### 嚴重度:一開始想錯了,查下去才是真的

第一版判斷是「§9.40 第二三題對 FM 是否」—— 因為 `refresh()` 有 try/catch,會把 TypeError 丟成 toast,看得見。

**但 `bind()` 不在那個保護裡。** 它有 17 個 `$("id").addEventListener(...)`,而呼叫點是:

```js
document.addEventListener("DOMContentLoaded", () => {
  bind();                       // 少一個 id 就在這裡 throw
  render(mock);                 // 不會執行
  refresh();                    // 不會執行
  setInterval(refresh, 900);    // 不會執行
});
```

順序決定一切:**bind() 排在最前面**,所以連 bind() 最後一個按鈕出事,輪詢都不會被排程。

#### 實測,不是推論

用 `http.server` 起真的頁面(`file://` 不行 —— 預覽窗把本機檔案當靜態快照,外部 script 根本不執行,`typeof $` 是 undefined)。

對照組:6 個 profile 鈕、3 個 model 鈕、GPU 名稱,都由 `render()` 填出來。

只把 `btn-quit` 打錯 —— **bind() 最後碰的那一個**:

```
profileBtns: 0        render(mock) 沒跑
modelBtns:   0
gpu:         "GPU"    靜態佔位字,從來沒被填
toast:       ""       沒有 toast:它在 refresh() 裡,而 refresh 沒開始
console:     TypeError: Cannot read properties of null
             (reading 'addEventListener')  at app.js:524:3
```

使用者看到:視窗開了、停在靜態骨架、沒有東西輪詢、下面每個控制項都沒綁定。Python 沒事、匣列沒事、`fluid_debug.log` 一個字都沒有。**唯一的痕跡在使用者永遠不會打開的 JS console 裡**,而那跟「還沒接上 mpv」長得一模一樣。

#### 守衛的唯一假設,自己也要釘

大部分查詢是靠比對 `$("...")` 找到的。**如果 `$` 哪天改包 `querySelector`,那些字串的意義就變了,而比對還會繼續通過。** 所以另外釘住 `$` 仍然是 `getElementById` 的包裝 —— 五個突變裡有兩個是打這一點的,都 CAUGHT。

#### AX 也加了,但份量不同

同一種形狀(`app.js:146` 的 `lib.addEventListener` 沒有 null 檢查),但壞的是行銷頁的示範,沒有人的安裝會壞。所以放進既有的 `test_public_surfaces.py`,不自成一檔。

理由是這頁真的會漂:版本號落後過兩個 release、授權對外說了十天的 MIT(§9.42)。**同一個手改檔案的第三種漂移不是假設。** 順手加了頁內連結檢查(skip link / 章節導軌 / 導覽列),死掉一個就是捲到不動,跟「沒有人點過」看起來一樣。

十個突變全 CAUGHT。148 / 306 passed,兩個直譯器皆綠。

#### 這一輪的方法論

**「0 個」和「全過」都要當成待證的數字。** 這一輪兩次靠這條救回來:FM 的 30 個 id 差點被記成 0,而 §9.41 那個 0.4 秒的測試差點被當成有在做事。

`.claude/launch.json` 多了一個 `fm-ui` 設定(port 8733,指向 `fluid_motion/ui`),留著讓這個驗證可以重跑。那個檔案是 gitignore 的,機器本地。
