
// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
let activeStatus = 'all';
let activeCategories = new Set(Object.keys(CATEGORY_COLORS));
let searchQuery = '';
let selectedTask = null;
let viewMode = 'treemap';
let generalistPicksActive = false;
let listSortCol = 'name';
let listSortDir = 'asc';

// Mobile default
if (window.innerWidth < 768) { viewMode = 'list'; }

// ─────────────────────────────────────────────────────────────────────────────
// Stats
// ─────────────────────────────────────────────────────────────────────────────
function updateStats() {
  const demonstrated = TASKS.filter(t => t.status === 'demonstrated');
  const nearTerm = TASKS.filter(t => t.status === 'near-term');
  const future = TASKS.filter(t => t.status === 'future');
  const allCompanies = new Set(TASKS.flatMap(t => t.companies));
  const allCategories = new Set(TASKS.map(t => t.category));
  const withVideos = TASKS.filter(t => t.videos && t.videos.length > 0);

  document.getElementById('stat-total').textContent = TASKS.length;
  document.getElementById('stat-demonstrated').textContent = demonstrated.length;
  document.getElementById('stat-pct').textContent = Math.round(demonstrated.length / TASKS.length * 100) + '%';
  document.getElementById('stat-nearterm').textContent = nearTerm.length;
  document.getElementById('stat-future').textContent = future.length;
  document.getElementById('stat-videos').textContent = withVideos.length;
  document.getElementById('stat-companies').textContent = allCompanies.size;
  document.getElementById('stat-categories').textContent = allCategories.size;
}

// ─────────────────────────────────────────────────────────────────────────────
// Category chips
// ─────────────────────────────────────────────────────────────────────────────
function buildCategoryChips() {
  const container = document.getElementById('category-filters');
  container.innerHTML = '';
  const categories = [...new Set(TASKS.map(t => t.category))];

  function updateChipStyles() {
    const allActive = activeCategories.size === categories.length;
    document.getElementById('cat-all-btn').classList.toggle('active', allActive);
    container.querySelectorAll('.cat-chip').forEach(chip => {
      const active = activeCategories.has(chip.dataset.cat);
      chip.classList.toggle('active', active);
      const color = CATEGORY_COLORS[chip.dataset.cat] || '#888';
      if (active) {
        chip.style.background = color + '30';
        chip.style.borderColor = color;
        chip.style.opacity = '1';
      } else {
        chip.style.background = 'transparent';
        chip.style.borderColor = color + '30';
        chip.style.opacity = '0.4';
      }
    });
  }

  const allBtn = document.createElement('button');
  allBtn.className = 'filter-btn active';
  allBtn.id = 'cat-all-btn';
  allBtn.textContent = 'All Categories';
  allBtn.style.fontSize = '11px';
  allBtn.addEventListener('click', () => {
    activeCategories = new Set(categories);
    updateChipStyles();
    applyFilters();
  });
  container.appendChild(allBtn);

  categories.forEach(cat => {
    const color = CATEGORY_COLORS[cat] || '#888';
    const chip = document.createElement('button');
    chip.className = 'cat-chip active';
    chip.dataset.cat = cat;
    chip.textContent = cat;
    chip.style.color = color;
    chip.style.background = color + '30';
    chip.style.borderColor = color;

    chip.addEventListener('click', () => {
      const allActive = activeCategories.size === categories.length;
      if (allActive) {
        // First click on any chip: switch to exclusive mode — show only this category
        activeCategories = new Set([cat]);
      } else if (activeCategories.has(cat) && activeCategories.size === 1) {
        // Clicking the only active chip: reset to all
        activeCategories = new Set(categories);
      } else if (activeCategories.has(cat)) {
        // Remove this one from multi-select
        activeCategories.delete(cat);
      } else {
        // Add to multi-select
        activeCategories.add(cat);
      }
      updateChipStyles();
      applyFilters();
    });
    container.appendChild(chip);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Treemap
// ─────────────────────────────────────────────────────────────────────────────
function getFilteredTasks() {
  return TASKS.filter(t => {
    const matchStatus = activeStatus === 'all' || t.status === activeStatus;
    const matchCat = activeCategories.has(t.category);
    const matchSearch = !searchQuery || 
      t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (t.description && t.description.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchGeneralist = !generalistPicksActive || 
      (t.status === 'near-term' && (t.dexterityRequired === 'high' || t.dexterityRequired === 'extreme'));
    return matchStatus && matchCat && matchSearch && matchGeneralist;
  });
}

const tooltip = document.getElementById('tooltip');

function showTooltip(event, task) {
  const statusClass = 'badge-' + task.status.replace('-', '-');
  const badgeClass = task.status === 'demonstrated' ? 'badge-demonstrated' :
                     task.status === 'near-term' ? 'badge-near-term' : 'badge-future';
  const statusLabel = task.status === 'demonstrated' ? 'Demonstrated' :
                      task.status === 'near-term' ? 'Near-Term' : 'Future';
  tooltip.innerHTML = `
    <div class="tt-name">${task.name}</div>
    <div class="tt-row">
      <span>${task.category}</span>
      <span class="tt-badge ${badgeClass}">${statusLabel}</span>
    </div>
    <div class="tt-row">
      <span>${task.companies.length} compan${task.companies.length !== 1 ? 'ies' : 'y'}</span>
      <span>TRL ${task.trl}</span>
    </div>
  `;
  tooltip.classList.add('visible');
  moveTooltip(event);
}

function moveTooltip(event) {
  const x = event.clientX + 14;
  const y = event.clientY - 10;
  const tw = tooltip.offsetWidth;
  const th = tooltip.offsetHeight;
  const wx = window.innerWidth;
  const wy = window.innerHeight;
  tooltip.style.left = (x + tw > wx ? event.clientX - tw - 14 : x) + 'px';
  tooltip.style.top = (y + th > wy ? event.clientY - th : y) + 'px';
}

function hideTooltip() {
  tooltip.classList.remove('visible');
}

function updateTreemap() {
  const filtered = getFilteredTasks();
  const emptyState = document.getElementById('empty-state');

  if (filtered.length === 0) {
    emptyState.classList.add('visible');
    d3.select('#treemap-svg').selectAll('*').remove();
    return;
  }
  emptyState.classList.remove('visible');

  const container = document.getElementById('treemap-container');
  const W = container.clientWidth;
  const H = container.clientHeight;

  const svg = d3.select('#treemap-svg')
    .attr('width', W)
    .attr('height', H);
  svg.selectAll('*').remove();

  // Build hierarchy: root → categories → tasks
  const grouped = d3.group(filtered, d => d.category);
  const rootData = {
    name: 'root',
    children: Array.from(grouped, ([cat, tasks]) => ({
      name: cat,
      children: tasks.map(t => ({
        name: t.name,
        value: t.companies.length + 1,
        task: t,
        category: cat
      }))
    }))
  };

  const root = d3.hierarchy(rootData)
    .sum(d => d.value)
    .sort((a, b) => b.value - a.value);

  d3.treemap()
    .tile(d3.treemapSquarify)
    .size([W - 2, H - 2])
    .paddingOuter(5)
    .paddingTop(24)
    .paddingInner(2)
    (root);

  // Draw category parent rects (background label area)
  root.children.forEach(catNode => {
    const color = CATEGORY_COLORS[catNode.data.name] || '#888';
    svg.append('rect')
      .attr('x', catNode.x0)
      .attr('y', catNode.y0)
      .attr('width', catNode.x1 - catNode.x0)
      .attr('height', catNode.y1 - catNode.y0)
      .attr('fill', color + '08')
      .attr('stroke', color + '20')
      .attr('stroke-width', 1)
      .attr('rx', 3);

    const catW = catNode.x1 - catNode.x0;
    const catH = catNode.y1 - catNode.y0;
    if (catW > 60 && catH > 24) {
      // Use a clipPath per category so text never bleeds outside its box
      const clipId = 'clip-cat-' + catNode.data.name.replace(/\W+/g, '-');
      svg.append('clipPath').attr('id', clipId)
        .append('rect')
          .attr('x', catNode.x0).attr('y', catNode.y0)
          .attr('width', catW - 4).attr('height', 20);
      svg.append('text')
        .attr('x', catNode.x0 + 6)
        .attr('y', catNode.y0 + 15)
        .attr('class', 'category-label')
        .attr('clip-path', `url(#${clipId})`)
        .style('fill', color)
        .style('opacity', 0.7)
        .text(catNode.data.name.toUpperCase());
    }
  });

  // Draw leaf cells
  const leaves = root.leaves();
  const cell = svg.selectAll('.cell')
    .data(leaves)
    .join('g')
    .attr('class', d => {
      const filtered = (activeStatus !== 'all' && d.data.task.status !== activeStatus) ||
                       !activeCategories.has(d.data.task.category);
      return 'cell' + (filtered ? ' filtered-out' : '');
    })
    .attr('transform', d => `translate(${d.x0},${d.y0})`);

  const color = CATEGORY_COLORS;

  cell.append('rect')
    .attr('width', d => Math.max(0, d.x1 - d.x0))
    .attr('height', d => Math.max(0, d.y1 - d.y0))
    .attr('rx', 2)
    .attr('class', d => `status-${d.data.task.status}`)
    .attr('fill', d => {
      const c = CATEGORY_COLORS[d.data.category] || '#888';
      return c + '18';
    })
    .attr('stroke', d => {
      const c = CATEGORY_COLORS[d.data.category] || '#888';
      if (d.data.task.status === 'demonstrated') return c;
      if (d.data.task.status === 'near-term') return c + '99';
      return '#555';
    })
    .style('stroke-dasharray', d => {
      if (d.data.task.status === 'near-term') return '5,3';
      if (d.data.task.status === 'future') return '2,4';
      return 'none';
    })
    .style('filter', d => {
      if (d.data.task.status === 'demonstrated') {
        const c = CATEGORY_COLORS[d.data.category] || '#888';
        return `drop-shadow(0 0 3px ${c}80)`;
      }
      return 'none';
    });

  // Task name labels — clip to cell so text never bleeds
  cell.each(function(d) {
    const w = d.x1 - d.x0;
    const h = d.y1 - d.y0;
    if (w * h < 1200 || w < 30 || h < 18) return;

    const g = d3.select(this);
    const taskName = d.data.task.name;
    const fontSize = Math.min(12, Math.max(8, Math.min(w / 8, h / 3)));
    const lineH = fontSize + 2;
    const maxLines = Math.floor((h - 8) / lineH);
    if (maxLines < 1) return;

    const lines = wrapText(taskName, w - 10);
    const visibleLines = lines.slice(0, maxLines);

    // Add clipPath so text is strictly contained
    const clipId = 'clip-cell-' + d.data.task.id;
    g.append('clipPath').attr('id', clipId)
      .append('rect').attr('width', w).attr('height', h);

    const totalTextH = visibleLines.length * lineH;
    const startY = Math.max(fontSize, (h - totalTextH) / 2 + fontSize);

    visibleLines.forEach((line, i) => {
      g.append('text')
        .attr('x', w / 2)
        .attr('y', startY + i * lineH)
        .attr('text-anchor', 'middle')
        .attr('clip-path', `url(#${clipId})`)
        .attr('font-size', fontSize)
        .attr('fill', 'rgba(255,255,255,0.88)')
        .attr('font-weight', '500')
        .text(line);
    });
  });

  // Events
  cell
    .on('mouseenter', function(event, d) {
      showTooltip(event, d.data.task);
      d3.select(this).select('rect').style('opacity', 0.9);
    })
    .on('mousemove', moveTooltip)
    .on('mouseleave', function() {
      hideTooltip();
      d3.select(this).select('rect').style('opacity', null);
    })
    .on('click', function(event, d) {
      openPanel(d.data.task);
    });
}

function wrapText(text, maxWidth) {
  const words = text.split(/\s+/);
  const approxCharWidth = 6.5;
  const lines = [];
  let current = '';
  for (const w of words) {
    const test = current ? current + ' ' + w : w;
    if (test.length * approxCharWidth > maxWidth && current) {
      lines.push(current);
      current = w;
    } else {
      current = test;
    }
  }
  if (current) lines.push(current);
  return lines;
}

// ─────────────────────────────────────────────────────────────────────────────
// Side panel
// ─────────────────────────────────────────────────────────────────────────────
function openPanel(task) {
  selectedTask = task;
  const panel = document.getElementById('side-panel');

  document.getElementById('panel-task-name').textContent = task.name;
  document.getElementById('panel-category').textContent = '📁 ' + task.category + (task.subcategory ? ' › ' + task.subcategory : '');

  const badgeClass = task.status === 'demonstrated' ? 'badge-demonstrated' :
                     task.status === 'near-term' ? 'badge-near-term' : 'badge-future';
  const statusLabel = task.status === 'demonstrated' ? '✅ Demonstrated' :
                      task.status === 'near-term' ? '🔬 Near-Term' : '🔭 Future';
  document.getElementById('panel-status').innerHTML = `<span class="tt-badge ${badgeClass}" style="font-size:12px;padding:4px 10px">${statusLabel}</span>`;

  const diffEl = document.getElementById('panel-difficulty');
  diffEl.innerHTML = '';
  for (let i = 1; i <= 5; i++) {
    const dot = document.createElement('div');
    dot.className = 'diff-dot ' + (i <= task.difficulty ? 'filled' : 'empty');
    diffEl.appendChild(dot);
  }
  const dexLabels = {low:'🤏 Low', medium:'✋ Medium', high:'💪 High', extreme:'🖐️ Extreme'};
  document.getElementById('panel-dexterity').textContent = dexLabels[task.dexterityRequired] || task.dexterityRequired;

  const trlPct = (task.trl / 9 * 100).toFixed(0);
  document.getElementById('panel-trl-bar').style.width = trlPct + '%';
  const trlLabels = {1:'Basic research',2:'Tech concept',3:'Proof of concept',4:'Lab validation',5:'Relevant environment',6:'Demonstrated',7:'Prototype complete',8:'Complete & qualified',9:'Operational'};
  document.getElementById('panel-trl-text').textContent = `TRL ${task.trl}/9 — ${trlLabels[task.trl] || ''}`;

  document.getElementById('panel-desc').textContent = task.description;

  const companiesEl = document.getElementById('panel-companies');
  companiesEl.innerHTML = '';
  if (task.companies.length === 0) {
    companiesEl.innerHTML = '<span style="color:var(--text-muted);font-size:12px">No public demos yet</span>';
  } else {
    task.companies.forEach(co => {
      const pill = document.createElement('span');
      pill.className = 'company-pill';
      pill.textContent = co;
      companiesEl.appendChild(pill);
    });
  }

  const tagsEl = document.getElementById('panel-tags');
  tagsEl.innerHTML = '';
  task.tags.forEach(tag => {
    const chip = document.createElement('span');
    chip.className = 'tag-chip';
    chip.textContent = '#' + tag;
    tagsEl.appendChild(chip);
  });

  const demoSection = document.getElementById('panel-demo-section');
  if (task.firstDemo) {
    demoSection.style.display = '';
    document.getElementById('panel-demo').textContent = task.firstDemo;
  } else {
    demoSection.style.display = 'none';
  }

  const sourceSection = document.getElementById('panel-source-section');
  if (task.sourceUrl) {
    sourceSection.style.display = '';
    document.getElementById('panel-source').innerHTML = `<a href="${task.sourceUrl}" target="_blank" rel="noopener">🔗 View source</a>`;
  } else {
    sourceSection.style.display = 'none';
  }

  // Video section — lazy thumbnail loading
  const videosSection = document.getElementById('panel-videos-section');
  const videosEl = document.getElementById('panel-videos');
  videosEl.innerHTML = '';
  if (task.videos && task.videos.length > 0) {
    videosSection.style.display = '';
    task.videos.forEach(v => {
      const wrapper = document.createElement('div');
      wrapper.style.cssText = 'margin-bottom:16px;';
      
      const typeLabel = document.createElement('div');
      typeLabel.style.cssText = 'font-size:11px;color:#999;margin-bottom:5px;display:flex;align-items:center;gap:5px;';
      typeLabel.innerHTML = `<span>${v.type === 'robot' ? '🤖 Robot Demo' : '👤 Human Tutorial'}</span><span style="color:#555">·</span><span>${v.label}</span>`;
      
      // Lazy thumbnail — click to load iframe
      const thumbWrapper = document.createElement('div');
      thumbWrapper.className = 'video-thumb-wrapper';
      thumbWrapper.innerHTML = `
        <img src="https://img.youtube.com/vi/${v.ytId}/hqdefault.jpg" alt="${v.label}" loading="lazy" onerror="this.src='https://img.youtube.com/vi/${v.ytId}/mqdefault.jpg'">
        <div class="video-play-btn">▶</div>
      `;
      thumbWrapper.addEventListener('click', function() {
        const iframeWrapper = document.createElement('div');
        iframeWrapper.className = 'video-iframe-wrapper';
        iframeWrapper.innerHTML = `<iframe src="https://www.youtube.com/embed/${v.ytId}?autoplay=1" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
        this.parentNode.replaceChild(iframeWrapper, this);
      });
      
      wrapper.appendChild(typeLabel);
      wrapper.appendChild(thumbWrapper);
      videosEl.appendChild(wrapper);
    });
  } else {
    videosSection.style.display = 'none';
  }

  // Why Generalist section
  const whySection = document.getElementById('panel-why-generalist');
  const whyText = document.getElementById('panel-why-text');
  if (task.status === 'near-term' && (task.dexterityRequired === 'high' || task.dexterityRequired === 'extreme')) {
    whySection.style.display = '';
    const dexStr = task.dexterityRequired === 'extreme' ? 'extreme dexterity' : 'high dexterity';
    const tagHighlights = task.tags.filter(t => ['bimanual','deformable','precision','force-control','fragile','tool-use'].includes(t)).slice(0,3);
    const tagStr = tagHighlights.length > 0 ? ` Involves ${tagHighlights.join(', ')}.` : '';
    whyText.innerHTML = `<strong>🎯 Generalist GEN-0 candidate.</strong> Near-term achievability + ${dexStr} = high-value demo target.${tagStr} TRL ${task.trl}/9 — close to demonstrable with current hardware.`;
  } else {
    whySection.style.display = 'none';
  }

  // Similar tasks section
  const similarEl = document.getElementById('panel-similar');
  const similar = TASKS.filter(t => t.id !== task.id && t.category === task.category)
    .sort((a,b) => {
      // Prefer tasks with same status
      const sameStatus = (t) => t.status === task.status ? 0 : 1;
      return sameStatus(a) - sameStatus(b);
    })
    .slice(0, 3);
  similarEl.innerHTML = '';
  similar.forEach(st => {
    const div = document.createElement('div');
    div.className = 'similar-task-link';
    const badgeClass = st.status === 'demonstrated' ? 'badge-demonstrated' : st.status === 'near-term' ? 'badge-near-term' : 'badge-future';
    const statusLabel = st.status === 'demonstrated' ? 'Demonstrated' : st.status === 'near-term' ? 'Near-Term' : 'Future';
    div.innerHTML = `<span>${st.name}</span><span class="similar-task-status tt-badge badge-sm ${badgeClass}">${statusLabel}</span>`;
    div.addEventListener('click', () => openPanel(st));
    similarEl.appendChild(div);
  });

  panel.classList.add('open');
  // Reflow treemap to account for panel
  setTimeout(updateTreemap, 310);
}

function closePanel() {
  document.getElementById('side-panel').classList.remove('open');
  selectedTask = null;
  setTimeout(updateTreemap, 310);
}

// ─────────────────────────────────────────────────────────────────────────────
// List View
// ─────────────────────────────────────────────────────────────────────────────
const DEX_ORDER = {low:1, medium:2, high:3, extreme:4};
const STATUS_ORDER = {demonstrated:1, 'near-term':2, future:3};

function getListValue(task, col) {
  switch(col) {
    case 'name': return task.name.toLowerCase();
    case 'category': return task.category;
    case 'status': return STATUS_ORDER[task.status] || 9;
    case 'dexterityRequired': return DEX_ORDER[task.dexterityRequired] || 0;
    case 'trl': return task.trl;
    case 'companies': return task.companies.length;
    case 'videos': return (task.videos||[]).length;
    default: return '';
  }
}

function updateListView() {
  const filtered = getFilteredTasks();
  const tbody = document.getElementById('list-tbody');
  
  // Sort
  filtered.sort((a, b) => {
    const av = getListValue(a, listSortCol);
    const bv = getListValue(b, listSortCol);
    const cmp = typeof av === 'string' ? av.localeCompare(bv) : (av - bv);
    return listSortDir === 'asc' ? cmp : -cmp;
  });
  
  tbody.innerHTML = '';
  filtered.forEach(task => {
    const tr = document.createElement('tr');
    const catColor = CATEGORY_COLORS[task.category] || '#888';
    const badgeClass = task.status === 'demonstrated' ? 'badge-demonstrated' :
                       task.status === 'near-term' ? 'badge-near-term' : 'badge-future';
    const statusLabel = task.status === 'demonstrated' ? 'Demo' :
                        task.status === 'near-term' ? 'Near' : 'Future';
    const dexLabels = {low:'Low', medium:'Med', high:'High', extreme:'Extreme'};
    const videoCount = (task.videos||[]).length;
    const firstCo = task.companies[0] || '';
    const coText = task.companies.length === 0 ? '—' :
                   task.companies.length === 1 ? firstCo :
                   firstCo.split(' ')[0] + ' +' + (task.companies.length-1);
    
    tr.innerHTML = `
      <td class="list-task-name">${task.name}</td>
      <td><div class="list-category-cell"><span class="list-category-dot" style="background:${catColor}"></span>${task.category}</div></td>
      <td><span class="tt-badge badge-sm ${badgeClass}">${statusLabel}</span></td>
      <td class="col-dex">${dexLabels[task.dexterityRequired] || task.dexterityRequired}</td>
      <td class="col-trl">${task.trl}/9</td>
      <td class="col-companies" style="color:var(--text-muted);font-size:12px">${coText}</td>
      <td class="col-videos list-video-icon ${videoCount > 0 ? 'has-video' : ''}">${videoCount > 0 ? '🎥 ' + videoCount : '—'}</td>
    `;
    tr.addEventListener('click', () => openPanel(task));
    tbody.appendChild(tr);
  });
  
  // Empty state for list
  if (filtered.length === 0) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="7" style="text-align:center;padding:40px;color:var(--text-muted)">No tasks match your filters.</td>';
    tbody.appendChild(tr);
  }
}

function setViewMode(mode) {
  viewMode = mode;
  const treemapContainer = document.getElementById('treemap-container');
  const listContainer = document.getElementById('list-container');
  const treemapBtn = document.getElementById('view-treemap-btn');
  const listBtn = document.getElementById('view-list-btn');
  
  if (mode === 'list') {
    treemapContainer.style.display = 'none';
    listContainer.classList.add('active');
    treemapBtn.classList.remove('active');
    listBtn.classList.add('active');
    updateListView();
  } else {
    treemapContainer.style.display = '';
    listContainer.classList.remove('active');
    treemapBtn.classList.add('active');
    listBtn.classList.remove('active');
    updateTreemap();
  }
}

function applyFilters() {
  if (viewMode === 'list') {
    updateListView();
  } else {
    updateTreemap();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event listeners
// ─────────────────────────────────────────────────────────────────────────────
document.getElementById('panel-close').addEventListener('click', closePanel);

document.getElementById('search-input').addEventListener('input', e => {
  searchQuery = e.target.value.trim();
  applyFilters();
});

// View toggle buttons
document.getElementById('view-treemap-btn').addEventListener('click', () => setViewMode('treemap'));
document.getElementById('view-list-btn').addEventListener('click', () => setViewMode('list'));

// Generalist Picks button
document.getElementById('generalist-picks-btn').addEventListener('click', () => {
  generalistPicksActive = !generalistPicksActive;
  const btn = document.getElementById('generalist-picks-btn');
  if (generalistPicksActive) {
    btn.classList.add('active');
    const count = TASKS.filter(t => t.status === 'near-term' && (t.dexterityRequired === 'high' || t.dexterityRequired === 'extreme')).length;
    btn.textContent = `🎯 Generalist Picks — ${count} tasks`;
  } else {
    btn.classList.remove('active');
    btn.textContent = '🎯 Generalist Picks';
  }
  applyFilters();
});

// List view sortable columns
document.querySelectorAll('#list-table th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (listSortCol === col) {
      listSortDir = listSortDir === 'asc' ? 'desc' : 'asc';
    } else {
      listSortCol = col;
      listSortDir = 'asc';
    }
    document.querySelectorAll('#list-table th').forEach(h => h.className = '');
    th.className = 'sort-' + listSortDir;
    updateListView();
  });
});

// Mobile filter toggle
const mobileToggle = document.getElementById('mobile-filter-toggle');
if (mobileToggle) {
  mobileToggle.addEventListener('click', () => {
    const catFilters = document.getElementById('category-filters');
    catFilters.classList.toggle('mobile-open');
  });
}

document.querySelectorAll('#status-filters .filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    activeStatus = btn.dataset.status;
    document.querySelectorAll('#status-filters .filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  });
});

// Resize
const ro = new ResizeObserver(() => { if (viewMode === 'treemap') updateTreemap(); });
ro.observe(document.getElementById('treemap-container'));

// ─────────────────────────────────────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────────────────────────────────────
updateStats();
buildCategoryChips();
// Initialize view
if (viewMode === 'list') {
  setViewMode('list');
} else {
  updateTreemap();
}
