(function(){
  'use strict';

  function byId(id){ return document.getElementById(id); }

  function parseJson(el, fallback){
    if(!el) return fallback;
    try { return JSON.parse(el.textContent || ''); } catch(e) { return fallback; }
  }

  function collectNodes(nodes, out){
    out = out || [];
    (nodes || []).forEach(function(node){
      out.push(node);
      if(node.children && node.children.length) collectNodes(node.children, out);
    });
    return out;
  }

  function findNode(nodes, id){
    var flat = collectNodes(nodes, []);
    for(var i = 0; i < flat.length; i++){
      if(flat[i].id === id) return flat[i];
    }
    return null;
  }

  function findParent(nodes, childId, parent){
    for(var i = 0; i < nodes.length; i++){
      var node = nodes[i];
      if(node.id === childId) return parent || null;
      if(node.children && node.children.length){
        var found = findParent(node.children, childId, node);
        if(found) return found;
      }
    }
    return null;
  }

  function getRootModule(nodes, nodeId){
    var node = findNode(nodes, nodeId);
    if(!node) return null;
    var parent = findParent(nodes, node.id);
    while(parent){
      node = parent;
      parent = findParent(nodes, node.id);
    }
    return node;
  }

  function escapeHtml(str){
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
  function escapeAttr(str){ return escapeHtml(str); }

  function initModuleAccess(){
    var root = byId('ma-access-root');
    if(!root) return;

    var treeData = parseJson(byId('ma-tree-data'), []);
    var initial = {
      dashboard_modules: parseJson(byId('ma-initial-dashboard'), []),
      sales_analytics_modules: parseJson(byId('ma-initial-sales-analytics'), []),
      user_access_modules: parseJson(byId('ma-initial-user-access'), []),
      payroll_modules: parseJson(byId('ma-initial-payroll'), []),
    };

    var scopeConfig = {};

    var state = {
      expanded: {},
      selectedId: treeData.length ? treeData[0].id : null,
      enabled: {},
      search: '',
    };

    var flatNodes = collectNodes(treeData, []);

    function getDescendants(node){
      var out = [];
      (node.children || []).forEach(function(child){
        out.push(child);
        out = out.concat(getDescendants(child));
      });
      return out;
    }

    function getPermissionDescendants(node){
      return getDescendants(node).filter(function(child){ return !isScopeNode(child); });
    }

    function isScopeNode(node){
      return !!(node && (node.scopeType || node.isAttendanceScope));
    }

    function nodeScopeType(node){
      if(!node) return '';
      return node.scopeType || (node.isAttendanceScope ? 'attendance' : '');
    }

    function isScopePermissionEnabled(scopeType){
      var cfg = scopeConfig[scopeType];
      return !!(cfg && state.enabled[cfg.parentId]);
    }

    function isScopeParentNode(node){
      if(!node) return false;
      return Object.keys(scopeConfig).some(function(scopeType){
        return scopeConfig[scopeType].parentId === node.id;
      });
    }

    function syncParentEnabledFromChildren(parent){
      if(isScopeParentNode(parent)) return;
      if(isScopeNode(parent)){
        var directChildren = parent.children || [];
        var anyScopeOn = directChildren.some(function(child){ return nodeEnabled(child); });
        state.enabled[parent.id] = anyScopeOn;
        return;
      }
      var descendants = getPermissionDescendants(parent);
      var anyOn = descendants.some(function(child){ return nodeEnabled(child); });
      state.enabled[parent.id] = anyOn;
    }

    function clearScope(scopeType){
      flatNodes.forEach(function(node){
        if(nodeScopeType(node) === scopeType) state.enabled[node.id] = false;
      });
    }

    var treeEl = byId('ma-tree');
    var summaryEl = byId('ma-summary');
    var hiddenEl = byId('ma-hidden-inputs');
    var searchEl = byId('ma-tree-search');
    var collapseBtn = byId('ma-collapse-all');

    function nodeEnabled(node){
      return !!state.enabled[node.id];
    }

    function isModuleAccessible(moduleNode){
      if(!moduleNode) return false;
      if(nodeEnabled(moduleNode)) return true;
      return getDescendants(moduleNode).some(function(child){ return nodeEnabled(child); });
    }

    function getCheckState(node){
      var descendants = isScopeNode(node)
        ? getDescendants(node)
        : getPermissionDescendants(node);
      if(!descendants.length){
        return nodeEnabled(node) ? 'checked' : 'unchecked';
      }
      var enabledCount = descendants.filter(function(child){ return nodeEnabled(child); }).length;
      if(enabledCount === 0 && !nodeEnabled(node)) return 'unchecked';
      if(enabledCount === descendants.length) return 'checked';
      return 'indeterminate';
    }

    function setDescendants(node, enabled){
      (node.children || []).forEach(function(child){
        state.enabled[child.id] = enabled;
        setDescendants(child, enabled);
      });
    }

    function syncAncestors(node){
      var parent = findParent(treeData, node.id);
      while(parent){
        syncParentEnabledFromChildren(parent);
        parent = findParent(treeData, parent.id);
      }
    }

    function ensureScopePermission(scopeType){
      var cfg = scopeConfig[scopeType];
      if(cfg && !isScopePermissionEnabled(scopeType)){
        state.enabled[cfg.parentId] = true;
        syncAncestors(findNode(treeData, cfg.parentId));
      }
    }

    function setNodeEnabled(node, enabled){
      if(isScopeNode(node) && enabled){
        ensureScopePermission(nodeScopeType(node));
      }
      Object.keys(scopeConfig).forEach(function(scopeType){
        if(node.id === scopeConfig[scopeType].parentId && !enabled) clearScope(scopeType);
      });
      state.enabled[node.id] = enabled;
      if(node.children && node.children.length){
        setDescendants(node, enabled);
      }
      syncAncestors(node);
      if(!enabled){
        var parentNode = findParent(treeData, node.id);
        while(parentNode){
          syncParentEnabledFromChildren(parentNode);
          parentNode = findParent(treeData, parentNode.id);
        }
      }
    }

    function syncParentFlags(){
      flatNodes.forEach(function(node){
        if(isScopeNode(node) || isScopeParentNode(node) || !node.children || !node.children.length) return;
        var descendants = getPermissionDescendants(node);
        var anyOn = descendants.some(function(child){ return nodeEnabled(child); });
        if(anyOn) state.enabled[node.id] = true;
      });
    }

    function syncHiddenInputs(){
      if(!hiddenEl) return;
      hiddenEl.innerHTML = '';
      var buckets = {};
      flatNodes.forEach(function(node){
        if(!state.enabled[node.id]) return;
        if(isScopeNode(node) && !isScopePermissionEnabled(nodeScopeType(node))) return;
        if(!node.fieldName || !node.fieldValue) return;
        if(!buckets[node.fieldName]) buckets[node.fieldName] = {};
        buckets[node.fieldName][node.fieldValue] = true;
      });
      Object.keys(buckets).forEach(function(name){
        Object.keys(buckets[name]).forEach(function(value){
          var input = document.createElement('input');
          input.type = 'hidden';
          input.name = name;
          input.value = value;
          hiddenEl.appendChild(input);
        });
      });
      document.dispatchEvent(new CustomEvent('ma-access-changed'));
    }

    flatNodes.forEach(function(node){
      var list = initial[node.fieldName] || [];
      state.enabled[node.id] = list.indexOf(node.fieldValue) !== -1;
    });

    syncParentFlags();

    function nodeIcon(node){
      if(node.icon && node.icon !== 'dot') return node.icon;
      if(node.children && node.children.length) return 'folder';
      return 'file';
    }

    function renderSummaryTree(nodes, depth){
      if(!nodes || !nodes.length) return '';
      var html = '<ul class="ma-summary-tree" data-depth="' + depth + '">';
      nodes.forEach(function(node, index){
        var isLast = index === nodes.length - 1;
        var enabled = nodeEnabled(node);
        var badge = enabled
          ? '<span class="ma-badge enabled">Enabled</span>'
          : '<span class="ma-badge disabled">Disabled</span>';
        var hasKids = node.children && node.children.length;
        html += '<li class="ma-summary-tree-node' + (isLast ? ' is-last' : '') + '" style="--depth:' + depth + '">';
        html += '<div class="ma-summary-tree-row">';
        html += '<span class="ma-summary-tree-icon"><i data-lucide="' + escapeAttr(nodeIcon(node)) + '"></i></span>';
        html += '<span class="ma-summary-tree-label">' + escapeHtml(node.label) + '</span>';
        html += badge;
        html += '</div>';
        if(hasKids) html += renderSummaryTree(node.children, depth + 1);
        html += '</li>';
      });
      html += '</ul>';
      return html;
    }

    function renderSummary(){
      if(!summaryEl) return;
      var selected = findNode(treeData, state.selectedId);
      var moduleRoot = getRootModule(treeData, state.selectedId) || selected;

      if(!moduleRoot){
        summaryEl.innerHTML = '<div class="ma-summary-empty"><i data-lucide="layout-grid"></i><p>Select a module to view access details.</p></div>';
        refreshIcons(summaryEl);
        return;
      }

      var displayNode = selected && selected.id !== moduleRoot.id ? selected : moduleRoot;
      var summaryChildren = (displayNode.children && displayNode.children.length)
        ? displayNode.children
        : (moduleRoot.children || []);

      var accessible = nodeEnabled(displayNode) || isModuleAccessible(displayNode);
      var badge = accessible
        ? '<span class="ma-badge enabled">Enabled</span>'
        : '<span class="ma-badge disabled">Disabled</span>';

      var desc = accessible
        ? (displayNode.description || moduleRoot.description || 'This module and all its enabled sub-modules are accessible.')
        : 'This module is currently disabled. Enable it in the tree to grant access.';

      var listHtml = '';
      if(summaryChildren.length){
        listHtml =
          '<div class="ma-summary-section">' +
            '<h4>' + (displayNode.id !== moduleRoot.id ? 'Included items' : 'Included sub-modules') + '</h4>' +
            '<div class="ma-summary-tree-wrap">' + renderSummaryTree(summaryChildren, 0) + '</div>' +
          '</div>';
      } else if(displayNode.id !== moduleRoot.id){
        listHtml =
          '<div class="ma-summary-section">' +
            '<h4>Module</h4>' +
            '<div class="ma-summary-tree-wrap">' + renderSummaryTree([displayNode], 0) + '</div>' +
          '</div>';
      } else {
        listHtml =
          '<div class="ma-summary-section">' +
            '<h4>Included sub-modules</h4>' +
            '<p class="ma-summary-empty-sub">No sub-modules available.</p>' +
          '</div>';
      }

      var icon = displayNode.icon && displayNode.icon !== 'dot'
        ? displayNode.icon
        : (moduleRoot.icon || 'layout-grid');

      summaryEl.innerHTML =
        '<div class="ma-summary-head">' +
          '<div class="ma-summary-icon"><i data-lucide="' + escapeAttr(icon) + '"></i></div>' +
          '<div class="ma-summary-title-wrap">' +
            '<div class="ma-summary-title-row">' +
              '<h3 class="ma-summary-title">' + escapeHtml(displayNode.label) + '</h3>' + badge +
            '</div>' +
            (displayNode.id !== moduleRoot.id
              ? '<p class="ma-summary-breadcrumb">' + escapeHtml(moduleRoot.label) + '</p>'
              : '') +
            '<p class="ma-summary-desc">' + escapeHtml(desc) + '</p>' +
          '</div>' +
        '</div>' + listHtml;

      refreshIcons(summaryEl);
    }

    function matchesSearch(node){
      if(!state.search) return true;
      var q = state.search.toLowerCase();
      if(node.label.toLowerCase().indexOf(q) !== -1) return true;
      if(node.children && node.children.length){
        return node.children.some(matchesSearch);
      }
      return false;
    }

    function renderTreeNode(node, depth){
      if(isScopeNode(node) && !isScopePermissionEnabled(nodeScopeType(node))){
        return '';
      }
      var hasChildren = node.children && node.children.length;
      var expanded = !!state.expanded[node.id];
      var selected = state.selectedId === node.id;
      var visible = matchesSearch(node);
      var checkState = getCheckState(node);
      var toggleClass = hasChildren ? (expanded ? 'is-expanded' : '') : 'is-empty';

      var html = '<li class="ma-tree-node" data-node-id="' + escapeAttr(node.id) + '" style="--depth:' + depth + '">';
      html += '<div class="ma-tree-row' + (selected ? ' is-selected' : '') + (!visible ? ' is-hidden' : '') + '" data-select-id="' + escapeAttr(node.id) + '">';
      html += '<button type="button" class="ma-tree-toggle ' + toggleClass + '" data-toggle-id="' + escapeAttr(node.id) + '" aria-label="Toggle ' + escapeAttr(node.label) + '" aria-expanded="' + (expanded ? 'true' : 'false') + '">';
      html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';
      html += '</button>';
      html += '<input type="checkbox" class="ma-tree-checkbox" data-check-id="' + escapeAttr(node.id) + '" data-check-state="' + checkState + '"' + (checkState === 'checked' ? ' checked' : '') + ' aria-label="Enable ' + escapeAttr(node.label) + '">';
      html += '<span class="ma-tree-node-icon"><i data-lucide="' + escapeAttr(nodeIcon(node)) + '"></i></span>';
      html += '<span class="ma-tree-label">' + escapeHtml(node.label) + '</span>';
      html += '</div>';

      if(hasChildren){
        var childHtml = '';
        node.children.forEach(function(child){
          childHtml += renderTreeNode(child, depth + 1);
        });
        html += '<ul class="ma-tree-children' + (expanded ? ' is-open' : '') + '" data-children-id="' + escapeAttr(node.id) + '">' + childHtml + '</ul>';
      }
      html += '</li>';
      return html;
    }

    function applyIndeterminate(){
      treeEl.querySelectorAll('[data-check-id]').forEach(function(input){
        var node = findNode(treeData, input.getAttribute('data-check-id'));
        if(!node) return;
        var checkState = getCheckState(node);
        input.checked = checkState === 'checked';
        input.indeterminate = checkState === 'indeterminate';
      });
    }

    function renderTree(){
      if(!treeEl) return;
      var html = '';
      treeData.forEach(function(node){
        html += renderTreeNode(node, 0);
      });
      treeEl.innerHTML = html;
      bindTreeEvents();
      applyIndeterminate();
      syncHiddenInputs();
      renderSummary();
      refreshIcons(treeEl);
    }

    function bindTreeEvents(){
      treeEl.querySelectorAll('[data-toggle-id]').forEach(function(btn){
        btn.addEventListener('click', function(e){
          e.stopPropagation();
          if(btn.classList.contains('is-empty')) return;
          var id = btn.getAttribute('data-toggle-id');
          state.selectedId = id;
          state.expanded[id] = !state.expanded[id];
          renderTree();
        });
      });

      treeEl.querySelectorAll('[data-select-id]').forEach(function(row){
        row.addEventListener('click', function(e){
          if(e.target.closest('.ma-tree-toggle') || e.target.closest('.ma-tree-checkbox')) return;
          state.selectedId = row.getAttribute('data-select-id');
          renderTree();
        });
      });

      treeEl.querySelectorAll('[data-check-id]').forEach(function(input){
        input.addEventListener('click', function(e){ e.stopPropagation(); });
        input.addEventListener('change', function(){
          var id = input.getAttribute('data-check-id');
          var node = findNode(treeData, id);
          if(!node) return;
          state.selectedId = id;
          var shouldEnable = input.checked;
          if(input.indeterminate) shouldEnable = true;
          setNodeEnabled(node, shouldEnable);
          if(shouldEnable && node.children && node.children.length){
            state.expanded[node.id] = true;
          }
          renderTree();
        });
      });
    }

    if(searchEl){
      searchEl.addEventListener('input', function(){
        state.search = (searchEl.value || '').trim().toLowerCase();
        if(state.search){
          flatNodes.forEach(function(node){
            if(node.children && node.children.length && matchesSearch(node)){
              state.expanded[node.id] = true;
            }
          });
        }
        renderTree();
      });
    }

    if(collapseBtn){
      collapseBtn.addEventListener('click', function(){
        state.expanded = {};
        renderTree();
      });
    }

    treeData.forEach(function(node){
      if(node.children && node.children.length){
        var any = isModuleAccessible(node);
        if(any) state.expanded[node.id] = true;
      }
      Object.keys(scopeConfig).forEach(function(scopeType){
        var cfg = scopeConfig[scopeType];
        var scopeParent = findNode(treeData, cfg.parentId);
        if(!scopeParent) return;
        var scopeSelected = getDescendants(scopeParent).some(function(child){
          return nodeScopeType(child) === scopeType && nodeEnabled(child);
        });
        if(isScopePermissionEnabled(scopeType) || scopeSelected){
          state.expanded[cfg.parentId] = true;
          (scopeParent.children || []).forEach(function(companyNode){
            if(nodeEnabled(companyNode) || getDescendants(companyNode).some(function(c){ return nodeEnabled(c); })){
              state.expanded[companyNode.id] = true;
            }
          });
        }
      });
    });

    renderTree();
  }

  function refreshIcons(scope){
    if(window.lucide && typeof window.lucide.createIcons === 'function'){
      window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }
  }

  document.addEventListener('DOMContentLoaded', initModuleAccess);
})();
