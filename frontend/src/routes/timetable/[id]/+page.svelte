<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import Modal from '#lib/components/Modal.svelte';
	import TimetableTree from '#lib/components/TimetableTree.svelte';
	import TimetableGrid from '#lib/components/TimetableGrid.svelte';
	import TimetableBlockEditor from '#lib/components/TimetableBlockEditor.svelte';
	import TimetableHours from '#lib/components/TimetableHours.svelte';
	import TimetableSettingsEditor from '#lib/components/TimetableSettings.svelte';
	import TimetableDiagnostics from '#lib/components/TimetableDiagnostics.svelte';
	import {
		timetableDiagnostics,
		diagnosticChanges,
		type DiagnosticEntry,
		type WarningEventTarget
	} from '#lib/timetableWarnings';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		timetableTree,
		nodeReceives,
		mondayOf,
		shiftTimetableDate,
		isoWeek,
		timetableConflictDetails,
		crossCalendarTeacherConflicts,
		teacherAvailabilityDetails,
		type TimetableBoard,
		type TimetableEvent,
		type TimetableBlock,
		type TimetableNode,
		type TimetableSettings,
		type TimetableWarning
	} from '#lib/timetable';
	import type { PageProps } from './$types';
	let { data }: PageProps = $props();
	let board = $state<TimetableBoard>({ years: [], events: [], members: [], warnings: [] });
	let date = $state('');
	let selectedKey = $state('promotion');
	let treeOpen = $state(false);
	let busy = $state(false);
	let loading = $state(true);
	let message = $state('');
	let notice = $state('');
	let editorOpen = $state(false);
	let editorMessage = $state('');
	let warningsOpen = $state(false);
	let hoursOpen = $state(false);
	let settingsOpen = $state(false);
	let editedSettings = $state<TimetableSettings | null>(null);
	let activeEvent = $state<TimetableEvent | null>(null);
	let detail = $state<TimetableEvent | null>(null);
	let clipboard = $state<TimetableBlock | null>(null);
	let scope = $state<'one' | 'future'>('future');
	let block = $state<TimetableBlock>({
		starts_on: '',
		start_slot: 0,
		duration_slots: 2,
		subject_id: null,
		teacher_id: null,
		room_id: null,
		kind: 'course',
		title: '',
		interval: 0,
		until: null,
		target_kind: 'promotion'
	});
	let pending = $state<{
		event: TimetableEvent | null;
		block: TimetableBlock | null;
		revision: string;
		changes: DiagnosticEntry[];
		ready: boolean;
		recurring: boolean;
	} | null>(null);
	let settingsConfirmation = $state(false);
	let settingsImpact = $state('');
	let requestNumber = 0;
	const administrator = $derived(data.catalog.administrator);
	const agenda = $derived({
		...data.agenda,
		...board.calendars?.find((item) => item.id === data.agenda.id)
	});
	const activeYear = $derived(board.years[0]);
	const editable = $derived(administrator && !agenda.is_archived);
	const live = $derived(!agenda.is_paused && agenda.promotion_id !== null);
	const promotionName = $derived(
		data.catalog.promotions.find((item) => item.id === agenda.promotion_id)?.name ?? agenda.name
	);
	const root = $derived(
		timetableTree(promotionName, agenda.promotion_id ?? 0, board.members, board.groups ?? [])
	);
	function flatten(node: TimetableNode): TimetableNode[] {
		return [node, ...node.children.flatMap(flatten)];
	}
	const selected = $derived(flatten(root).find((node) => node.key === selectedKey) ?? root);
	const displayedEvents = $derived(
		board.events.filter((event) => nodeReceives(event, selected, board.members))
	);
	const week = $derived(date ? mondayOf(date) : '');
	const warnings = $derived<TimetableWarning[]>([
		...timetableConflictDetails(board.events, board.groups ?? [], data.catalog.today),
		...crossCalendarTeacherConflicts(
			board.events,
			board.teacher_commitments ?? [],
			data.catalog.today
		),
		...teacherAvailabilityDetails(
			board.events,
			board.availability ?? [],
			data.catalog.today,
			activeYear?.school_year
		)
	]);
	const issues = $derived(board.issues ?? []);
	const warningCount = $derived(warnings.length + issues.length);
	$effect(() => {
		const id = data.agenda.id;
		void untrack(() => refresh(id));
	});
	async function readBoard(id = agenda.id): Promise<TimetableBoard> {
		const query = new URLSearchParams({ calendar_ids: String(id) });
		const response = await fetch(resolve('/timetable/data') + '?' + query);
		const result = (await response.json()) as TimetableBoard & { message?: string };
		if (!response.ok) throw new Error(result.message ?? 'Chargement impossible.');
		return result;
	}
	async function refresh(id = agenda.id): Promise<void> {
		const request = ++requestNumber;
		loading = true;
		try {
			const result = await readBoard(id);
			if (request !== requestNumber) return;
			board = result;
			if (!date && result.years[0])
				date =
					data.catalog.today >= result.years[0].settings.start &&
					data.catalog.today <= result.years[0].settings.end
						? data.catalog.today
						: result.years[0].settings.start;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Chargement impossible.';
		} finally {
			if (request === requestNumber) loading = false;
		}
	}
	function select(node: TimetableNode): void {
		selectedKey = node.key;
		treeOpen = false;
	}
	function create(day: string, slot: number): void {
		if (!editable || !activeYear) return;
		activeEvent = null;
		scope = 'future';
		editorMessage = '';
		const group = ['halves', 'thirds', 'kholles', 'custom'].includes(selected.kind);
		block = {
			starts_on: day,
			start_slot: slot,
			duration_slots: Math.min(2, activeYear.slots.length - slot),
			subject_id: null,
			teacher_id: null,
			room_id: null,
			kind: 'course',
			title: '',
			interval: 1,
			until: activeYear.settings.end,
			target_kind: group ? selected.kind : 'promotion',
			target_number: group ? selected.number : null,
			target_user_id: null
		};
		editorOpen = true;
	}
	function eventFields(event: TimetableEvent): TimetableBlock {
		const source = activeYear?.series.find((item) => item.id === event.series_id);
		return {
			starts_on: event.start.slice(0, 10),
			start_slot: event.start_slot,
			duration_slots: event.duration_slots,
			start_time: event.start_time ?? null,
			end_time: event.end_time ?? null,
			subject_id: event.subject_id,
			teacher_id: event.teacher_id,
			room_id: event.room_id,
			kind: event.kind,
			title: source?.exceptions[event.source_date]?.title ?? source?.title ?? event.title,
			interval: source?.interval ?? 0,
			until: source?.until ?? activeYear?.settings.end ?? null,
			target_kind: event.target_kind ?? 'promotion',
			target_number: event.target_number ?? null,
			target_user_id: event.target_user_id ?? null
		};
	}
	function edit(event: TimetableEvent): void {
		if (!editable) {
			detail = event;
			return;
		}
		activeEvent = event;
		block = eventFields(event);
		scope = 'future';
		editorMessage = '';
		editorOpen = true;
	}
	function copy(event: TimetableEvent): void {
		if (editable) {
			clipboard = eventFields(event);
			notice = 'Séance copiée.';
		}
	}
	function paste(day: string, slot: number): void {
		if (!editable || !clipboard || !activeYear) return;
		activeEvent = null;
		scope = 'future';
		editorMessage = '';
		block = {
			...structuredClone($state.snapshot(clipboard)),
			starts_on: day,
			start_slot: slot,
			duration_slots: Math.min(clipboard.duration_slots, activeYear.slots.length - slot),
			interval: 1,
			until: activeYear.settings.end
		};
		if (clipboard.start_time !== null && clipboard.start_time !== undefined) {
			block.start_time = activeYear.slots[slot][0];
			block.end_time =
				block.start_time + (clipboard.end_time ?? clipboard.start_time) - clipboard.start_time;
		}
		editorOpen = true;
	}
	function chooseKind(kind: TimetableBlock['kind']): void {
		block.kind = kind;
	}
	async function requestSave(remove = false, fields = block, event = activeEvent): Promise<void> {
		if (!editable || !activeYear?.revision || busy) return;
		const revision = activeYear.revision;
		busy = true;
		editorMessage = '';
		message = '';
		try {
			const recurring =
				!!event && !!activeYear.series.find((item) => item.id === event.series_id)?.interval;
			const candidate = remove ? null : structuredClone($state.snapshot(fields));
			const diagnostics = await previewDiagnostics(candidate, event, 'one', revision);

			pending = {
				event,
				block: candidate,
				revision,
				changes: diagnostics,
				ready: true,
				recurring
			};
			scope = 'one';
		} catch (cause) {
			editorMessage = message = cause instanceof Error ? cause.message : 'Vérification impossible.';
		} finally {
			busy = false;
		}
	}
	async function previewDiagnostics(
		fields: TimetableBlock | null,
		event: TimetableEvent | null,
		applyScope: 'one' | 'future',
		revision: string
	): Promise<DiagnosticEntry[]> {
		if (!activeYear) return [];
		const baseline = await readBoard();
		if (baseline.years[0]?.revision !== revision)
			throw new Error('Le calendrier a changé. Rechargez-le avant de continuer.');
		const preview = await timetableCommand<TimetableBoard>(
			'years/' + activeYear.id + '/preview',
			'POST',
			{
				expected_revision: revision,
				series_id: event?.series_id ?? null,
				occurrence: event?.source_date ?? null,
				scope: applyScope,
				block: fields
			}
		);
		const source = baseline.years
			.flatMap((year) => year.series)
			.find((series) => series.id === event?.series_id);
		const focus = {
			event,
			block: fields,
			scope: (source?.interval === 0 && fields?.interval ? 'future' : applyScope) as
				'one' | 'future',
			originalSeries: baseline.years.flatMap((year) => year.series.map((series) => series.id))
		};
		return diagnosticChanges(
			timetableDiagnostics(baseline, data.catalog.today, focus),
			timetableDiagnostics(preview, data.catalog.today, focus)
		);
	}
	async function chooseScope(value: 'one' | 'future'): Promise<void> {
		if (!pending || busy) return;
		pending.ready = false;
		scope = value;
		busy = true;
		message = '';
		try {
			const diagnostics = await previewDiagnostics(
				pending.block,
				pending.event,
				value,
				pending.revision
			);
			pending.changes = diagnostics;
			pending.ready = true;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Vérification impossible.';
		} finally {
			busy = false;
		}
	}
	async function confirmSave(): Promise<void> {
		if (!pending || !pending.ready || !activeYear) return;
		busy = true;
		message = '';
		editorMessage = '';
		const change = pending;
		try {
			if (change.event)
				await timetableCommand(
					'years/' + activeYear.id + '/series/' + change.event.series_id,
					'PUT',
					{
						expected_revision: change.revision,
						confirmed_live: true,
						occurrence: change.event.source_date,
						scope: change.recurring ? scope : 'one',
						block: change.block
					}
				);
			else if (change.block)
				await timetableCommand('years/' + activeYear.id + '/series', 'POST', {
					expected_revision: change.revision,
					confirmed_live: true,
					block: change.block
				});
			pending = null;
			editorOpen = false;
			notice = 'Calendrier enregistré' + (live ? ' et diffusé.' : '.');
			await refresh();
		} catch (cause) {
			editorMessage = message =
				cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	function move(
		event: TimetableEvent,
		day: string,
		slot: number,
		duration?: number,
		exact?: { start: number; end: number }
	): void {
		const fields = {
			...eventFields(event),
			starts_on: day,
			start_slot: slot,
			...(duration ? { duration_slots: duration } : {})
		};
		if (exact) {
			fields.start_time = exact.start;
			fields.end_time = exact.end;
		}
		void requestSave(false, fields, event);
	}
	function openSettings(): void {
		if (activeYear) {
			editedSettings = structuredClone($state.snapshot(activeYear.settings));
			settingsOpen = true;
		}
	}
	async function requestSettings(): Promise<void> {
		if (!editedSettings || !activeYear) return;
		busy = true;
		message = '';
		try {
			const result = (await timetableCommand(
				'years/' + activeYear.id + '/settings/preview',
				'POST',
				{
					expected_revision: activeYear.revision,
					settings: editedSettings
				}
			)) as { hidden?: number; added?: number };
			settingsImpact =
				(result.hidden ?? 0) +
				' segment(s) retiré(s) de l’affichage et des compteurs ; ' +
				(result.added ?? 0) +
				' segment(s) ajouté(s). Les données et exceptions seront conservées.';
			settingsConfirmation = true;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Prévisualisation impossible.';
		} finally {
			busy = false;
		}
	}
	async function saveSettings(): Promise<void> {
		if (!editedSettings || !activeYear) return;
		busy = true;
		try {
			await timetableCommand('years/' + activeYear.id + '/settings', 'PUT', {
				expected_revision: activeYear.revision,
				confirmed_live: true,
				settings: editedSettings
			});
			settingsConfirmation = false;
			settingsOpen = false;
			await refresh();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
	function openWarningEvent(target: WarningEventTarget): void {
		warningsOpen = false;
		date = target.event.start.slice(0, 10);
		edit(target.event);
	}
</script>

<svelte:window
	onfocus={() => {
		if (!busy && !editorOpen && !pending && !settingsOpen) void refresh();
	}}
/>
<svelte:head
	><title>{agenda.name} — {data.establishmentName}</title><meta
		name="description"
		content="Emploi du temps annuel de la promotion."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<section class="calendar-workspace" aria-label={'Calendrier ' + agenda.name}>
	<header class="workspace-toolbar">
		<a class="back" href={resolve('/timetable')} aria-label="Retour aux agendas">←</a><button
			class="tree-toggle"
			aria-label="Afficher les groupes"
			aria-expanded={treeOpen}
			onclick={() => (treeOpen = !treeOpen)}>☰</button
		>
		<div class="workspace-name">
			<h1>{agenda.name}</h1>
			<span>{selected.label} · {activeYear?.school_year}/{(activeYear?.school_year ?? 0) + 1}</span>
		</div>
		<div class="week-navigation">
			<button
				aria-label="Semaine précédente"
				disabled={busy || loading || !date}
				onclick={() => (date = shiftTimetableDate(date, -7))}>‹</button
			><button class="today-button" onclick={() => (date = data.catalog.today)}>Aujourd’hui</button
			><button
				aria-label="Semaine suivante"
				disabled={busy || loading || !date}
				onclick={() => (date = shiftTimetableDate(date, 7))}>›</button
			>
		</div>
		<label class="week-label"
			><span
				>{activeYear?.weeks[week] ? 'Semaine ' + activeYear.weeks[week] : 'Hors cours'} (ISO {date
					? isoWeek(date)
					: ''})</span
			><input
				type="date"
				aria-label="Date affichée"
				bind:value={date}
				min={activeYear?.settings.start}
				max={activeYear?.settings.end}
			/></label
		>
		<div class="toolbar-spacer"></div>
		{#if editable && activeYear}<button
				class="button is-small is-light"
				disabled={busy}
				onclick={openSettings}>Réglages</button
			><button
				class="button is-small is-light"
				aria-label="Ajouter une séance"
				disabled={busy}
				onclick={() => create(date, 0)}>+</button
			>{/if}
		<button
			class="warning-button"
			class:clear={warningCount === 0}
			class:critical={issues.some((i) => i.severity === 'critical') ||
				warnings.some((w) => w.severity === 'critical')}
			onclick={() => (warningsOpen = true)}
			aria-label={'Points à vérifier (' + warningCount + ')'}>⚠ {warningCount}</button
		>
		{#if activeYear}<button class="button is-small is-light" onclick={() => (hoursOpen = true)}
				>▥ Heures</button
			>{/if}
	</header>
	<p class="publication-help">
		{agenda.is_archived
			? 'Archive · lecture seule · diffusion coupée'
			: live
				? 'Diffusé en direct : chaque enregistrement met à jour les consultations et abonnements ICS.'
				: 'Diffusion coupée : le calendrier reste accessible aux administrateurs.'}
	</p>
	{#if message && !pending && !settingsOpen}<div class="workspace-message" role="alert">
			{message}
		</div>{/if}{#if notice}<span class="workspace-notice" role="status">{notice}</span>{/if}
	<div class="workspace-body">
		<aside class="resource-sidebar" class:mobile-open={treeOpen}>
			<TimetableTree {root} selected={selected.key} onselect={select} />
		</aside>
		<div class="calendar-area" aria-busy={loading}>
			{#if loading}<div class="calendar-empty" role="status">
					Chargement…
				</div>{:else if activeYear}<TimetableGrid
					years={[activeYear]}
					events={displayedEvents}
					{date}
					editable={editable && !busy}
					canPaste={!!clipboard && editable}
					oncopy={copy}
					onpaste={paste}
					oncreate={create}
					onopen={edit}
					onmove={move}
					onresize={move}
				/>{:else}<div class="calendar-empty">Aucun calendrier disponible.</div>{/if}
		</div>
	</div>
</section>
{#if editorOpen && activeYear}<TimetableBlockEditor
		bind:block
		year={activeYear}
		catalog={data.catalog}
		groups={board.groups ?? []}
		promotionId={agenda.promotion_id}
		existing={!!activeEvent}
		{busy}
		message={editorMessage}
		currentTeacherName={activeEvent?.teacher ?? ''}
		onclose={() => (editorOpen = false)}
		onkindchange={chooseKind}
		onsave={() => void requestSave()}
		onremove={() => void requestSave(true)}
	/>{/if}
{#if pending}<Modal
		title={pending.block ? 'Enregistrer la séance' : 'Supprimer la séance'}
		{busy}
		onclose={() => (pending = null)}
	>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		{#if live}<p class="notification is-warning is-light">
				Ce calendrier est diffusé en direct. Le changement sera immédiatement visible par ses
				destinataires et dans les abonnements ICS.
			</p>{/if}
		{#if pending.recurring}<label class="scope-switch">
				<input
					type="checkbox"
					role="switch"
					aria-label="Inclure les occurrences suivantes"
					checked={scope === 'future'}
					disabled={busy}
					onchange={(event) => void chooseScope(event.currentTarget.checked ? 'future' : 'one')}
				/>
				<span
					>{pending.block ? 'Modifier' : 'Supprimer'}
					{scope === 'future'
						? 'cet événement et toutes les occurrences à venir'
						: 'uniquement cet événement'}</span
				>
			</label>{:else}<p>
				Confirmer {pending.block ? 'l’enregistrement' : 'la suppression'} de cette séance ?
			</p>{/if}
		{#if activeYear}<TimetableDiagnostics
				entries={pending.changes}
				changes
				year={activeYear}
				catalog={data.catalog}
			/>{/if}
		<div class="buttons mt-5">
			<button class="button is-primary" disabled={busy || !pending.ready} onclick={confirmSave}
				>Confirmer</button
			><button class="button is-light" disabled={busy} onclick={() => (pending = null)}
				>Annuler</button
			>
		</div>
	</Modal>{/if}
{#if settingsOpen && editedSettings}<Modal
		title="Réglages du calendrier"
		{busy}
		onclose={() => (settingsOpen = false)}
		><form
			onsubmit={(event) => {
				event.preventDefault();
				void requestSettings();
			}}
		>
			{#if message}<p class="notification is-danger is-light" role="alert">
					{message}
				</p>{/if}<TimetableSettingsEditor bind:settings={editedSettings} locked /><button
				class="button is-primary mt-5"
				disabled={busy}>Vérifier les changements</button
			>
		</form></Modal
	>{/if}
{#if settingsConfirmation}<Modal
		title="Appliquer les changements de calendrier"
		{busy}
		onclose={() => (settingsConfirmation = false)}
		><p>{settingsImpact}</p>
		<p class="mt-3">
			Les alternances et compteurs annuels seront recalculés.{live
				? ' Le calendrier est diffusé : les destinataires verront immédiatement les changements.'
				: ''}
		</p>
		{#if message}<p class="notification is-danger is-light mt-3" role="alert">
				{message}
			</p>{/if}<button class="button is-primary mt-5" disabled={busy} onclick={saveSettings}
			>Confirmer</button
		></Modal
	>{/if}
{#if warningsOpen && activeYear}<Modal
		title="Points à vérifier"
		onclose={() => (warningsOpen = false)}
		><TimetableDiagnostics
			entries={timetableDiagnostics(board, data.catalog.today)}
			year={activeYear}
			catalog={data.catalog}
			onopen={openWarningEvent}
		/></Modal
	>{/if}
{#if hoursOpen && activeYear}<Modal title="Heures par matière" onclose={() => (hoursOpen = false)}
		><TimetableHours
			hours={activeYear.hours ?? []}
			subjects={data.catalog.subjects}
			weeks={Object.keys(activeYear.weeks).length}
		/></Modal
	>{/if}
{#if detail}<Modal title={detail.title} onclose={() => (detail = null)}
		><p>{detail.start.slice(0, 10)} · {detail.start.slice(11, 16)}–{detail.end.slice(11, 16)}</p>
		<p class="mt-3">{detail.teacher} · {detail.room}</p></Modal
	>{/if}

<style>
	.scope-switch {
		display: flex;
		align-items: center;
		gap: 0.9rem;
		margin: 1.25rem 0;
		line-height: 1.5;
		cursor: pointer;
	}
	.scope-switch input {
		appearance: none;
		flex-shrink: 0;
		width: 42px;
		height: 24px;
		border-radius: 24px;
		background: var(--color-border);
		position: relative;
		cursor: pointer;
	}
	.scope-switch input::after {
		content: '';
		position: absolute;
		width: 18px;
		height: 18px;
		top: 3px;
		left: 3px;
		border-radius: 50%;
		background: var(--color-surface);
		transition: transform 0.15s;
	}
	.scope-switch input:checked {
		background: var(--color-primary);
	}
	.scope-switch input:checked::after {
		transform: translateX(18px);
	}
	.scope-switch input:focus-visible {
		outline: 3px solid var(--color-primary);
		outline-offset: 3px;
	}
	.scope-switch input:disabled {
		opacity: 0.5;
		cursor: wait;
	}
	.calendar-workspace {
		height: 100dvh;
		display: flex;
		flex-direction: column;
		background: var(--color-surface);
		overflow: hidden;
	}
	.workspace-toolbar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		min-height: 65px;
		padding: 0.65rem 0.8rem;
		border-bottom: var(--border-thin);
		flex: none;
	}
	.back {
		color: var(--color-ink);
		font-size: 1.4rem;
		padding: 0.3rem;
	}
	.workspace-name {
		min-width: 130px;
		margin-right: 0.5rem;
	}
	h1 {
		font-size: 1rem;
		font-weight: 700;
		line-height: 1.3;
	}
	.workspace-name span {
		display: block;
		color: var(--color-muted);
		font-size: 0.73rem;
	}
	.toolbar-spacer {
		flex: 1;
	}
	.week-navigation {
		display: flex;
		gap: 3px;
	}
	.week-navigation button,
	.tree-toggle {
		border: 0;
		background: none;
		color: inherit;
		cursor: pointer;
		padding: 0.2rem 0.5rem;
		font-size: 1.3rem;
	}
	.week-navigation .today-button {
		font-size: 0.8rem;
	}
	.week-label {
		display: flex;
		flex-direction: column;
		font-size: 0.7rem;
		color: var(--color-muted);
	}
	.week-label input {
		width: 125px;
		font: inherit;
		color: var(--color-ink);
		border: 0;
		background: none;
	}
	.publication-help {
		padding: 0.35rem 0.8rem;
		color: var(--color-muted);
		background: var(--color-subtle);
		font-size: 0.75rem;
		border-bottom: var(--border-thin);
		flex: none;
	}
	.workspace-body {
		position: relative;
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.resource-sidebar {
		width: 245px;
		flex: none;
		border-right: var(--border-thin);
		display: flex;
		flex-direction: column;
		background: var(--color-surface);
		min-height: 0;
	}
	.calendar-area {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
	}
	.calendar-empty {
		display: flex;
		height: 100%;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 2rem;
		color: var(--color-muted);
		text-align: center;
	}
	.workspace-message {
		padding: 0.55rem 1rem;
		color: var(--color-danger);
		background: var(--color-danger-soft);
		font-size: 0.85rem;
	}
	.workspace-notice {
		position: absolute;
		bottom: 16px;
		right: 24px;
		padding: 0.5rem 0.8rem;
		font-size: 0.8rem;
		background: var(--color-success-soft);
		color: var(--color-success);
		border-radius: 7px;
		z-index: 5;
		pointer-events: none;
	}
	.warning-button {
		border: 0;
		color: var(--color-warning);
		background: var(--color-warning-soft);
		border-radius: 6px;
		padding: 0.4rem;
		cursor: pointer;
	}
	.warning-button.clear {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.warning-button.critical {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}
	.tree-toggle {
		display: none;
	}
	@media (max-width: 1100px) {
		.workspace-toolbar {
			flex-wrap: wrap;
			gap: 0.4rem;
		}
		.resource-sidebar {
			width: 210px;
		}
	}
	@media (max-width: 760px) {
		.tree-toggle {
			display: block;
		}
		.resource-sidebar {
			display: none;
		}
		.resource-sidebar.mobile-open {
			display: flex;
			position: absolute;
			top: 0;
			bottom: 0;
			left: 0;
			width: 260px;
			z-index: 8;
			box-shadow: var(--shadow-panel);
		}
		.workspace-name {
			min-width: 100px;
		}
		.workspace-toolbar {
			min-height: 100px;
		}
		.workspace-toolbar :global(.button) {
			font-size: 0.7rem;
		}
		.toolbar-spacer {
			display: none;
		}
	}
</style>
