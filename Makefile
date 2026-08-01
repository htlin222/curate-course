PY := uv run python
COURSE ?= course
DIST ?= dist
PORT ?= 8899
CHROME ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
# 進版控的那一份才是本體：dist/ 被 gitignore，重新 clone 之後只有這裡的圖還在。
# build.py 的 sync_web() 會把 $(COURSE)/assets/ 複製進 $(DIST)，所以 /og.png 自然可用。
OG_PNG := $(COURSE)/assets/og.png
PROJECT ?= $(shell $(PY) -c "import json;print(json.load(open('$(COURSE)/course.config.json'))['site']['project'])")

export COURSE
export DIST

.DEFAULT_GOAL := help

help: ## 列出可用指令
	@grep -E '^[a-z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build: ## 合併資料 → public/course.json，含配額驗證與 SEO 產出
	$(PY) src/build/build.py

icons: ## 重新下載 Lucide 圖示並打包成內嵌 sprite
	$(PY) src/build/build_icons.py

og: build ## 用 headless Chrome 重新產生社群預覽圖（截圖來源是 build 注入好數值的 $(DIST)/og.html）
	@test -x "$(CHROME)" || { echo "✗ 找不到 Chrome：$(CHROME)（用 make og CHROME=... 指定）"; exit 1; }
	@command -v magick > /dev/null || { echo "✗ 找不到 magick（brew install imagemagick）"; exit 1; }
	@mkdir -p $(dir $(OG_PNG))
	@"$(CHROME)" \
		--headless --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
		--window-size=1200,630 --screenshot="$(abspath $(OG_PNG))" "$(abspath $(DIST)/og.html)"
	@magick $(OG_PNG) -resize 1200x630 -strip $(OG_PNG)
	@cp $(OG_PNG) $(DIST)/og.png
	@echo "→ $(OG_PNG)（記得 git add）· 已同步一份到 $(DIST)/og.png"

counter: ## 建立瀏覽次數用的 D1 資料庫並寫出 wrangler 綁定（冪等，可重跑）
	$(PY) src/build/setup_counter.py

audit: ## 離線稽核設定檔、配額、影片長度與實證深度（確定性，不打網路）
	$(PY) src/build/audit.py

test: ## 前端純邏輯的單元測試（零依賴、不需要瀏覽器）
	node --test 'tests/*.test.js'

e2e: build ## paywall 端對端流程並截圖到 .tmp/paywall-shots（需要 Chrome）
	@mkdir -p .tmp
	@$(PY) -m http.server $(PORT) --directory $(DIST) > /dev/null 2>&1 & \
		echo $$! > .tmp/serve.pid
	@sleep 1
	@NODE_PATH=$$(npm root -g) node tests/e2e-paywall.cjs; \
		status=$$?; kill `cat .tmp/serve.pid` 2>/dev/null; rm -f .tmp/serve.pid; exit $$status

verify: ## 重驗所有影片連結與 PubMed 引用（打真實 API，會跑一陣子）
	$(PY) src/build/verify_links.py
	$(PY) src/build/verify_refs.py

serve: ## 本機預覽
	@echo "→ http://localhost:$(PORT)"
	@$(PY) -m http.server $(PORT) --directory $(DIST)

deploy: build ## 建置後部署到 Cloudflare Pages
	npm exec --yes -- wrangler@4 pages deploy $(DIST) \
		--project-name $(PROJECT) --branch main --commit-dirty=true

lint: ## ruff 檢查
	uv run ruff check .

fmt: ## ruff 格式化
	uv run ruff format .
	uv run ruff check --fix .

# build 排在 test 前面：有一部分測試是拿 dist/ 的產出物（JSON-LD、og.html）
# 跟 course.json 對數字，沒先 build 就只能整組跳過。
check: lint build test audit ## 提交前跑這個（含單元測試與離線稽核）

clean: ## 清掉建置暫存
	rm -rf .tmp .wrangler .ruff_cache dist **/__pycache__

.PHONY: help build icons og counter audit test e2e verify serve deploy lint fmt check clean
