(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = { file: null, source: null, total: 0, complete: 0, answers: new Map(), queue: new Map(), startedAt: 0 };

  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const money = (amount) => '$' + Number(amount || 0).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  const pretty = (value) => String(value || '').replaceAll('_',' ').replace(/\b\w/g, (s) => s.toUpperCase());
  const setMessage = (message, error = false) => { $('form-message').textContent = message; $('form-message').classList.toggle('is-error', error); };

  async function checkApi() {
    try {
      const response = await fetch('/api/health');
      const payload = await response.json();
      $('api-dot').parentElement.classList.add('connected');
      $('api-label').textContent = 'Console API ready';
      if (payload.graph_configured) $('graph-label').textContent = `TigerGraph ${payload.graph_name} is configured. A live count is checked when the run starts.`;
      else $('graph-label').textContent = 'Add TG_HOST and TG_SECRET to .env to run against TigerGraph.';
    } catch (_) {
      $('api-dot').parentElement.classList.add('error');
      $('api-label').textContent = 'API unavailable';
      $('graph-label').textContent = 'Start the FastAPI service to enable live investigations.';
    }
  }

  function setFile(file) {
    if (!file) return;
    state.file = file;
    $('file-name').innerHTML = `<strong>${escape(file.name)}</strong> <u>change</u>`;
    $('run-button').disabled = false;
    setMessage(`${(file.size / 1024).toFixed(1)} KB · ready to validate`);
  }

  $('case-file').addEventListener('change', (event) => setFile(event.target.files[0]));
  const drop = $('dropzone');
  for (const name of ['dragenter','dragover']) drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.add('dragover'); });
  for (const name of ['dragleave','drop']) drop.addEventListener(name, (event) => { event.preventDefault(); drop.classList.remove('dragover'); });
  drop.addEventListener('drop', (event) => setFile(event.dataTransfer.files[0]));

  $('sample-button').addEventListener('click', async () => {
    try {
      const response = await fetch('/api/case-pack');
      if (!response.ok) throw new Error((await response.json()).detail || 'Could not load sample case pack');
      const blob = await response.blob();
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'case_pack.csv';
      link.click();
      URL.revokeObjectURL(link.href);
      setMessage('Downloaded the current case_pack.csv sample.');
    } catch (error) { setMessage(error.message, true); }
  });

  $('run-button').addEventListener('click', startRun);

  async function startRun() {
    if (!state.file) return;
    $('run-button').disabled = true;
    state.answers.clear(); state.queue.clear(); state.complete = 0; state.startedAt = Date.now();
    $('case-queue').innerHTML = '<div class="empty-queue">Validating uploaded CSV…</div>';
    $('stage-list').innerHTML = '<li class="current"><span class="stage-marker"></span><span>Uploading and validating the case pack</span></li>';
    $('result-content').className = 'result-empty';
    $('result-content').textContent = 'Waiting for the first case to finish…';
    $('result-title').textContent = 'Live results';
    $('result-metrics').textContent = '';
    $('run-title').textContent = 'Starting investigation run';
    $('run-count').textContent = 'Connecting to TigerGraph';
    $('queue-label').textContent = 'Preparing';
    $('progress-bar').style.width = '0%';
    setMessage('Validating CSV and connecting to the live graph…');

    const form = new FormData();
    form.append('file', state.file);
    form.append('graphrag_mode', $('mode-select').value);
    try {
      const response = await fetch('/api/investigations/run', {method:'POST', body:form});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Could not start the run');
      state.total = result.total;
      (result.case_ids || []).forEach((caseId, index) => state.queue.set(caseId, {status:'queued', index:index + 1}));
      renderQueue();
      $('run-count').textContent = `0 / ${state.total} complete`;
      $('queue-label').textContent = `${state.total} cases queued`;
      state.source = new EventSource(result.stream_url);
      state.source.onmessage = (event) => handleEvent(JSON.parse(event.data));
      state.source.onerror = () => {
        if (state.source && state.source.readyState === EventSource.CLOSED) state.source.close();
      };
    } catch (error) {
      setMessage(error.message, true);
      $('run-title').textContent = 'Run could not start';
      $('run-count').textContent = 'Check setup';
      $('run-button').disabled = false;
      $('stage-list').innerHTML = `<li class="failed"><span class="stage-marker"></span><span>${escape(error.message)}</span></li>`;
    }
  }

  function handleEvent(event) {
    switch (event.type) {
      case 'run_started':
        $('run-title').textContent = 'Investigation in progress';
        break;
      case 'graph_connecting':
        $('run-count').textContent = `Connecting · ${escape(event.graph)}`;
        break;
      case 'graph_connected':
        $('api-dot').parentElement.classList.add('connected');
        $('graph-label').textContent = `Connected to ${event.graph} · ${Number(event.transaction_count).toLocaleString()} transactions`;
        $('run-count').textContent = `${Number(event.transaction_count).toLocaleString()} graph transactions · ${pretty(event.mode)} context`;
        $('result-metrics').textContent = `Providers: ${(event.providers || []).join(' → ') || 'configured fallback'}`;
        break;
      case 'case_started':
        state.queue.set(event.case_id, {...(state.queue.get(event.case_id) || {}), status:'running', index:event.index, trigger:event.trigger});
        $('activity-label').textContent = `${event.case_id} · ${event.index}/${event.total}`;
        $('stage-list').innerHTML = '';
        addStage(`Investigating ${event.case_id}`, 'current');
        renderQueue();
        break;
      case 'stage':
        if (event.case_id === $('activity-label').textContent.split(' · ')[0]) addStage(event.label, 'current');
        break;
      case 'case_completed':
        state.complete = event.index;
        state.answers.set(event.case_id, event.answer);
        state.queue.set(event.case_id, {...(state.queue.get(event.case_id) || {}), status:'done', index:event.index, answer:event.answer});
        $('progress-bar').style.width = `${Math.round(state.complete / state.total * 100)}%`;
        $('run-count').textContent = `${state.complete} / ${state.total} complete`;
        $('queue-label').textContent = `${state.complete} completed · ${state.total - state.complete} remaining`;
        renderQueue();
        showAnswer(event.case_id, event.answer);
        break;
      case 'case_failed':
        state.queue.set(event.case_id, {status:'failed', index:event.index, error:event.error});
        addStage(`Case failed: ${event.error}`, 'failed');
        renderQueue();
        break;
      case 'run_completed':
        $('run-title').textContent = 'Run complete';
        $('queue-label').textContent = `Answers saved to ${event.output_dir}`;
        setMessage(`Finished ${event.completed} case${event.completed === 1 ? '' : 's'}. Original cases/ answers were not overwritten.`);
        $('run-button').disabled = !state.file;
        if (state.source) state.source.close();
        break;
      case 'run_failed':
        $('run-title').textContent = 'Run stopped';
        $('queue-label').textContent = 'Review the error below';
        setMessage(event.error, true);
        $('run-button').disabled = !state.file;
        if (state.source) state.source.close();
        break;
    }
  }

  function addStage(label, status) {
    const list = $('stage-list');
    const previous = list.querySelector('li.current');
    if (previous && status === 'current') { previous.classList.remove('current'); previous.classList.add('done'); }
    if (status === 'current' && [...list.children].some((item) => item.textContent.includes(label))) return;
    const li = document.createElement('li');
    li.className = status;
    li.innerHTML = `<span class="stage-marker"></span><span>${escape(label)}</span><time class="stage-time">${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}</time>`;
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
  }

  function renderQueue() {
    if (!state.queue.size) return;
    $('case-queue').innerHTML = [...state.queue.entries()].map(([id, item]) => {
      const answer = item.answer || {};
      const verdict = answer.case?.verdict;
      const stateLabel = item.status === 'running' ? 'RUNNING' : item.status === 'failed' ? 'FAILED' : verdict ? verdict.toUpperCase() : 'QUEUED';
      return `<button class="queue-case ${item.status}" data-id="${escape(id)}"><span><strong>${escape(id)}</strong><small>${escape(item.trigger || answer.case?.pattern || '')}</small></span><span class="queue-state">${escape(stateLabel)}</span></button>`;
    }).join('');
    $('case-queue').querySelectorAll('.queue-case').forEach((button) => button.addEventListener('click', () => {
      const answer = state.answers.get(button.dataset.id);
      if (answer) showAnswer(button.dataset.id, answer);
    }));
  }

  function actionList(actions) {
    if (!actions?.length) return '<p class="muted">No actions recorded.</p>';
    return actions.map((item) => `<div class="action-line"><b>${escape(item.action)}</b><span>${escape(item.route)}</span><small>${escape(item.reason)}</small></div>`).join('');
  }

  function showAnswer(caseId, answer) {
    const c = answer.case || {}, sar = answer.sar || {}, actions = answer.next_best_actions || {};
    $('result-title').textContent = `Investigation · ${caseId}`;
    $('result-content').className = 'result-card';
    $('result-content').innerHTML = `
      <div class="result-card-head"><span class="case-id">${escape(caseId)}</span><span class="tag ${escape(c.verdict)}">${escape(pretty(c.verdict))}</span><span class="tag">${escape(pretty(c.pattern))}</span><span class="tag">${escape(pretty(c.status))}</span>${c.written_to_graph ? `<span class="tag graph">✓ Written to graph · ${escape(c.graph_case_id)}</span>` : ''}</div>
      <div class="trigger-box"><small>${escape(pretty(answer.trigger_type || 'Case trigger'))}</small>${escape(answer.trigger_text || 'Uploaded case-pack row')}</div>
      <div class="result-columns"><section class="result-block"><h3>Evidence gathered · ${(c.evidence || []).length}</h3>${(c.evidence || []).map((item, i) => `<div class="evidence-row"><p>${i + 1}. ${escape(item.claim)}</p><small>${escape(item.source)} · ${escape(item.ref)}<span class="entity-list">${(item.entity_ids || []).length ? ' · ' + item.entity_ids.map(escape).join(', ') : ''}</span></small></div>`).join('') || '<p class="muted">No evidence listed.</p>'}</section>
      <section class="result-block"><h3>Next best actions</h3><div class="action-col"><strong>Initial · before evidence</strong>${actionList(actions.initial)}</div><div class="action-col"><strong>Final · after evidence</strong>${actionList(actions.final)}</div>${actions.what_changed && actions.what_changed !== 'nothing' ? `<p class="muted">↗ ${escape(actions.what_changed)}</p>` : ''}</section></div>
      ${answer.evidence_requests?.length ? `<section class="result-block" style="margin-top:14px"><h3>Evidence requests · simulated</h3>${answer.evidence_requests.map((req) => `<div class="evidence-row"><p>${escape(pretty(req.type))}</p><small>${escape(req.assumed_response)}</small></div>`).join('')}</section>` : ''}
      ${sar.file ? `<section class="result-block sar-block"><h3>Suspicious Activity Report · ${escape(sar.reason)}</h3><div class="sar-copy">${escape(sar.narrative)}</div><div class="result-foot"><span>Subjects: ${(sar.subjects || []).map(escape).join(', ')}</span><span>Amount: ${money(sar.total_amount_usd)}</span><span>Dates: ${(sar.activity_dates || []).map(escape).join(' – ')}</span></div></section>` : ''}
      <section class="result-block" style="margin-top:14px"><h3>Agent summary</h3><p class="summary-copy">${escape(c.summary)}</p><div class="result-foot"><span>Stop: ${escape(answer.stop_reason)}</span><span>${Number(answer.tool_calls || 0)} graph/tool calls</span><span>${Number(answer.tokens || 0).toLocaleString()} tokens</span><span>${Number(answer.latency_s || 0).toFixed(1)} sec</span></div></section>`;
    document.querySelectorAll('.queue-case').forEach((button) => button.classList.toggle('selected', button.dataset.id === caseId));
  }

  checkApi();
})();
