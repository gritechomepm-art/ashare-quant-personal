"""Build-only presentation guard for the old full-function app.

SOURCE index.html and its strategy definitions remain byte-identical. This patch
only affects the generated site/app.html display of TODAY's daily screening,
never the historical backtest/signal ledger or manual stock analysis.
"""
def patch_full_app_for_mainboard(html):
    def replace_once(before, after):
        nonlocal html
        count = html.count(before)
        if count != 1:
            raise ValueError("Cannot safely patch published full-app screen; matches="+str(count))
        html = html.replace(before, after)

    replace_once(
        "function rowsForScreen(){",
        "function isMainBoardRow(row){return /^(?:600|601|603|605|000|001|002|003)\\d{3}$/.test(String(row?.code||''));}\nfunction rowsForScreen(){"
    )
    replace_once(
        "return (screen.rows||[]).filter(s=>(filter==='all'",
        "return (screen.rows||[]).filter(s=>isMainBoardRow(s)&&(filter==='all'"
    )
    replace_once(
        ".filter(row=>rowInPriceRange(row)).map(row=>({row,state:liveBuyState(row)}))",
        ".filter(row=>isMainBoardRow(row)&&rowInPriceRange(row)).map(row=>({row,state:liveBuyState(row)}))"
    )
    replace_once(
        "<div class=\"hrow\"><h2>观察清单</h2><span id=\"listTotal\">0只</span></div>",
        "<div class=\"hrow\"><h2>沪深主板观察清单</h2><span id=\"listTotal\">0只</span></div>\n"
        '<p class="fine">每日选股仅沪深主板（600/601/603/605、000/001/002/003，含原中小板）；创业板、科创板、北交所不参与。历史研究与已锁档数据保持原样。</p>'
    )
    replace_once(
        " $('coverage').textContent=screen.covered_count>=0&&screen.eligible_count?fmt(screen.coverage_pct,1)+'%':'—';",
        " $('coverage').textContent=screen.board_scope==='SH_SZ_MAIN'&&screen.covered_count>=0&&screen.eligible_count?fmt(screen.coverage_pct,1)+'%':'—';"
    )
    replace_once(
        " $('coverageDesc').textContent=screen.eligible_count?screen.covered_count+'/'+screen.eligible_count+'只合格股票':'历史数据未就绪';",
        " $('coverageDesc').textContent=screen.board_scope==='SH_SZ_MAIN'&&screen.eligible_count?screen.covered_count+'/'+screen.eligible_count+'只主板候选':'旧全市场覆盖率待主板重算';"
    )
    replace_once(
        " $('signalsCount').textContent=screen.status==='uninitialized'?'—':(screen.buy_watch_count??'待更新');",
        " $('signalsCount').textContent=screen.status==='uninitialized'?'—':(screen.rows||[]).filter(s=>isMainBoardRow(s)&&s.entry_signal===true).length;"
    )
    replace_once(
        " $('coverageBar').style.width=Math.min(100,Math.max(0,Number(screen.coverage_pct)||0))+'%';",
        " $('coverageBar').style.width=(screen.board_scope==='SH_SZ_MAIN'?Math.min(100,Math.max(0,Number(screen.coverage_pct)||0)):0)+'%';"
    )
    replace_once(
        " $('universeStatus').textContent=screen.eligible_count?'符合基础条件 '+screen.eligible_count+'只，已计算 '+screen.covered_count+'只':'等待自动任务采集';",
        " $('universeStatus').textContent=screen.board_scope==='SH_SZ_MAIN'&&screen.eligible_count?'主板符合基础条件 '+screen.eligible_count+'只，已计算 '+screen.covered_count+'只':'主板专属覆盖率待下一次盘后生成';"
    )
    replace_once(
        ":screen.status==='complete'?'<strong>本批股票池已完成：",
        ":screen.board_scope!=='SH_SZ_MAIN'?'<strong>旧快照提示：</strong>全市场旧数据已按主板代码过滤展示；正式主板覆盖率待下一次盘后重算。':screen.status==='complete'?'<strong>本批主板股票池已完成："
    )
    replace_once(
        " $('dateChip').textContent=screen.asof?`收盘选股截至 ${screen.asof} · ${screen.covered_count||0}/${screen.eligible_count||0} 只已覆盖`:'盘后筛选待初始化';",
        " $('dateChip').textContent=screen.asof?(screen.board_scope==='SH_SZ_MAIN'?`主板收盘选股截至 ${screen.asof} · ${screen.covered_count||0}/${screen.eligible_count||0} 只已覆盖`:'旧快照：仅显示主板，覆盖待重算'):'盘后筛选待初始化';"
    )
    return html
