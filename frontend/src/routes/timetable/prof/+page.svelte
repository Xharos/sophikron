<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import TimetableGrid from '#lib/components/TimetableGrid.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import TeacherHours from '#lib/components/TeacherHours.svelte';
	import {
		clockSeconds,
		eventTeacherIds,
		preferredSchoolYear,
		currentSchoolYear,
		mondayOf,
		shiftTimetableDate,
		timetableClock,
		type AvailabilityRange,
		type TimetableEvent,
		type TimetableYear
	} from '#lib/timetable';
	import {
		selectTeachers,
		teacherColor,
		teacherCalendarColor,
		type TeacherBoard
	} from '#lib/teacherTimetable';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let yearNumber = $state(0);
	let selectedIds = $state<number[]>([]);
	let mode = $state<'availability' | 'timetable'>('timetable');
	let editing = $state(false);
	let board = $state<TeacherBoard>({ availability: [], events: [] });
	let date = $state('');
	let search = $state('');
	let loading = $state(false);
	let busy = $state(false);
	let message = $state('');
	let notice = $state('');
	let sidebarOpen = $state(false);
	let hoursOpen = $state(false);
	let ctrlLeft = $state(false);
	let editorOpen = $state(false);
	let rangeIndex = $state<number | null>(null);
	let weekday = $state(0);
	let rangeStart = $state('08:00:00');
	let rangeEnd = $state('09:00:00');
	let rangeMessage = $state('');
	let detail = $state<TimetableEvent | null>(null);
	let requestNumber = 0;
	let kholleMinHours = $state<number | undefined>(0);
	let kholleMaxHours = $state<number | undefined>(0);
	const administrator = $derived(data.catalog.administrator);
	const annual = $derived(data.catalog.years.find((year) => year.school_year === yearNumber));
	const single = $derived(selectedIds.length === 1 ? selectedIds[0] : null);
	const pattern = $derived(board.availability.find((item) => item.teacher_id === single));
	const selectedTeachers = $derived(
		data.catalog.teachers.filter((teacher) => selectedIds.includes(teacher.id))
	);
	const selectedName = $derived(selectedTeachers.map((teacher) => teacher.name).join(', '));
	const canEdit = $derived(
		administrator && single !== null && mode === 'availability' && !loading && !busy && !!pattern
	);
	const monday = $derived(mondayOf(date || data.catalog.today));
	const weekEvents = $derived(
		board.events.filter(
			(event) =>
				event.start.slice(0, 10) >= monday &&
				event.start.slice(0, 10) < shiftTimetableDate(monday, 7)
		)
	);
	const gridYear = $derived<TimetableYear | null>(
		annual
			? {
					...annual,
					id: 0,
					calendar_id: 0,
					revision: null,
					weeks: {},
					series: []
				}
			: null
	);
	const availabilityEvents = $derived<TimetableEvent[]>(
		pattern
			? pattern.ranges.map((range, index) => {
					const day = shiftTimetableDate(monday, range.weekday);
					return {
						id: `availability-${index}`,
						series_id: String(index),
						source_date: day,
						start: `${day}T${timetableClock(range.start)}`,
						end: `${day}T${timetableClock(range.end)}`,
						start_slot: 0,
						duration_slots: 1,
						subject_id: null,
						teacher_id: single,
						room_id: null,
						kind: 'course',
						title: 'Disponible',
						color: teacherColor(single ?? 0),
						teacher: selectedName,
						room: '',
						calendar_id: 0,
						promotion_id: null,
						year_id: 0
					};
				})
			: []
	);
	const displayedEvents = $derived(
		mode === 'availability'
			? availabilityEvents
			: weekEvents.map((event) => ({
					...event,
					color: teacherCalendarColor(
						single ?? eventTeacherIds(event).find((id) => selectedIds.includes(id)) ?? 0,
						event.calendar_id
					)
				}))
	);
	const folders = $derived(
		[
			...data.catalog.subjects.map((subject) => ({
				...subject,
				teachers: data.catalog.teachers.filter((teacher) =>
					teacher.subject_ids?.includes(subject.id)
				)
			})),
			{
				id: 0,
				name: 'Sans matière',
				color: '#64748B',
				teachers: data.catalog.teachers.filter((teacher) => !teacher.subject_ids?.length)
			}
		]
			.map((folder) => ({
				...folder,
				teachers: folder.teachers
					.filter((teacher) =>
						`${folder.name} ${teacher.name}`
							.toLocaleLowerCase('fr-FR')
							.includes(search.toLocaleLowerCase('fr-FR'))
					)
					.sort((a, b) => a.name.localeCompare(b.name, 'fr'))
			}))
			.filter((folder) => folder.teachers.length)
			.sort((a, b) => a.name.localeCompare(b.name, 'fr'))
	);

	$effect(() => {
		if (!yearNumber && data.catalog.years.length) {
			yearNumber = preferredSchoolYear(data.catalog.years, data.catalog.today);
			date =
				yearNumber === currentSchoolYear(data.catalog.today)
					? data.catalog.today
					: data.catalog.years.find((year) => year.school_year === yearNumber)!.settings.start;
			const initialTeacher =
				data.catalog.teachers.find((teacher) => teacher.id === data.user?.id) ??
				data.catalog.teachers[0];
			selectedIds = initialTeacher ? [initialTeacher.id] : [];
		}
	});
	$effect(() => {
		const year = yearNumber;
		const ids = [...selectedIds];
		void mode;
		if (year && ids.length) void untrack(() => refresh(year, ids));
		else {
			requestNumber++;
			board = { availability: [], events: [] };
			loading = false;
		}
	});
	async function refresh(
		year = yearNumber,
		ids = selectedIds,
		preserveHours = editing
	): Promise<void> {
		const request = ++requestNumber;
		loading = true;
		message = '';
		try {
			const query = new URLSearchParams({
				school_year: String(year),
				teacher_ids: ids.join(','),
				include_occupancy: String(mode === 'availability')
			});
			const response = await fetch(`${resolve('/timetable/prof/data')}?${query}`);
			const result = (await response.json()) as TeacherBoard & { message?: string };
			if (request !== requestNumber) return;
			if (!response.ok) throw new Error(result.message ?? 'Chargement impossible.');
			board = result;
			if (!preserveHours) {
				const saved = result.availability.find((item) => item.teacher_id === single);
				kholleMinHours = saved?.kholle_min_hours ?? 0;
				kholleMaxHours = saved?.kholle_max_hours ?? 0;
			}
		} catch (cause) {
			if (request === requestNumber) {
				message = cause instanceof Error ? cause.message : 'Chargement impossible.';
				board = { availability: [], events: [] };
			}
		} finally {
			if (request === requestNumber) loading = false;
		}
	}
	function select(ids: number[], additive: boolean, subjectFolder = false): void {
		if (busy) return;
		const same = !additive && ids.length === 1 && single === ids[0];
		selectedIds = selectTeachers(selectedIds, ids, additive);
		editing = false;
		if (subjectFolder || selectedIds.length !== 1) mode = 'timetable';
		else if (same) mode = mode === 'availability' ? 'timetable' : 'availability';
		notice = '';
	}
	function changeYear(value: number): void {
		yearNumber = value;
		const year = data.catalog.years.find((item) => item.school_year === value);
		date =
			year && year.settings.start <= data.catalog.today && data.catalog.today <= year.settings.end
				? data.catalog.today
				: (year?.settings.start ?? data.catalog.today);
		editing = false;
		notice = '';
	}
	function changeMode(value: typeof mode): void {
		mode = value;
		editing = false;
		notice = '';
	}
	function navigate(days: number): void {
		if (!annual) return;
		const value = shiftTimetableDate(date, days);
		date =
			value < annual.settings.start
				? annual.settings.start
				: value > annual.settings.end
					? annual.settings.end
					: value;
	}
	async function save(
		ranges: AvailabilityRange[] | null | undefined,
		hours?: { kholle_min_hours: number; kholle_max_hours: number }
	): Promise<boolean> {
		if (!canEdit || !pattern || single === null) return false;
		busy = true;
		message = rangeMessage = '';
		try {
			const query = new URLSearchParams({
				school_year: String(yearNumber),
				teacher_id: String(single)
			});
			const response = await fetch(`${resolve('/timetable/prof/data')}?${query}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ expected_revision: pattern.revision, ranges, ...hours })
			});
			const result = (await response.json()) as { message?: string };
			if (!response.ok) throw new Error(result.message ?? 'Enregistrement impossible.');
			await refresh(yearNumber, selectedIds, !hours && editing);
			notice = hours ? 'Bornes de khôlles enregistrées.' : 'Disponibilités enregistrées.';
			return true;
		} catch (cause) {
			message = rangeMessage =
				cause instanceof Error ? cause.message : 'Enregistrement impossible.';
			return false;
		} finally {
			busy = false;
		}
	}
	async function toggleEditing(): Promise<void> {
		if (!canEdit) return;
		if (!editing) {
			editing = true;
			return;
		}
		if (
			kholleMinHours === undefined ||
			kholleMaxHours === undefined ||
			!Number.isInteger(kholleMinHours) ||
			!Number.isInteger(kholleMaxHours) ||
			kholleMinHours < 0 ||
			kholleMaxHours > 2147483647 ||
			kholleMaxHours < kholleMinHours
		) {
			message = 'Saisissez des heures entières avec 0 ≤ minimum ≤ maximum.';
			return;
		}
		if (
			await save(undefined, { kholle_min_hours: kholleMinHours, kholle_max_hours: kholleMaxHours })
		)
			editing = false;
	}
	function openRange(index: number | null, day = 0, start?: number, end?: number): void {
		if (!editing || !canEdit || !annual) return;
		const range = index !== null ? pattern?.ranges[index] : null;
		rangeIndex = index;
		weekday = range?.weekday ?? day;
		const closing = weekday === 5 ? 43200 : 68400;
		if (!range && (start ?? 28800) >= closing) return;
		rangeStart = timetableClock(range?.start ?? start ?? annual.settings.day_start);
		rangeEnd = timetableClock(
			range?.end ??
				end ??
				Math.min(closing, clockSeconds(rangeStart) + annual.settings.session_minutes * 60)
		);
		rangeMessage = '';
		editorOpen = true;
	}
	async function submitRange(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!pattern) return;
		const range = { weekday, start: clockSeconds(rangeStart), end: clockSeconds(rangeEnd) };
		if (range.start >= range.end) {
			rangeMessage = 'La fin doit suivre le début.';
			return;
		}
		const ranges = pattern.ranges.filter((_, index) => index !== rangeIndex);
		if (await save([...ranges, range])) editorOpen = false;
	}
	function rangeChanged(event: TimetableEvent, day: string, start: number, end: number): void {
		if (!pattern || !editing || !annual) return;
		const range = { weekday: (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7, start, end };
		void save([...pattern.ranges.filter((_, index) => index !== Number(event.series_id)), range]);
	}
	function createAt(day: string, slot: number): void {
		if (!annual) return;
		const start = annual.slots[slot]?.[0] ?? annual.settings.day_start;
		openRange(null, (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7, start);
	}
</script>

<svelte:head
	><title>prof — {data.establishmentName}</title><meta
		name="description"
		content="Disponibilités annuelles et emplois du temps des enseignants."
	/><meta name="robots" content="noindex, nofollow" /></svelte:head
>
<svelte:window
	onkeydown={(event) => {
		if (event.code === 'ControlLeft') ctrlLeft = true;
	}}
	onkeyup={(event) => {
		if (event.code === 'ControlLeft') ctrlLeft = false;
	}}
	onblur={() => {
		ctrlLeft = false;
	}}
/>

<div class="calendar-workspace">
	<header class="workspace-toolbar">
		<a class="back" href={resolve('/timetable')} aria-label="Revenir aux agendas">←</a>
		<button
			class="button is-small is-light tree-toggle"
			aria-label="Afficher les enseignants"
			aria-expanded={sidebarOpen}
			onclick={() => (sidebarOpen = !sidebarOpen)}>☰</button
		>
		<div class="workspace-name">
			<h1>prof</h1>
			<span>Agenda permanent</span>
		</div>
		<select
			class="year-select"
			aria-label="Année scolaire"
			value={yearNumber}
			disabled={busy}
			onchange={(event) => changeYear(Number(event.currentTarget.value))}
		>
			{#each data.catalog.years as year (year.school_year)}<option value={year.school_year}
					>{year.school_year}/{year.school_year + 1}</option
				>{/each}
		</select>
		<div class="buttons has-addons mode-buttons" role="group" aria-label="Mode de consultation">
			<button
				class="button is-small"
				class:is-primary={mode === 'availability'}
				aria-pressed={mode === 'availability'}
				disabled={single === null || busy}
				onclick={() => changeMode('availability')}>Disponibilités</button
			>
			<button
				class="button is-small"
				class:is-primary={mode === 'timetable'}
				aria-pressed={mode === 'timetable'}
				disabled={busy}
				onclick={() => changeMode('timetable')}>Emploi du temps</button
			>
		</div>
		{#if administrator && single !== null && mode === 'availability'}<button
				class="button is-small"
				class:is-primary={editing}
				disabled={!canEdit}
				onclick={toggleEditing}
				>{editing ? 'Terminer l’édition' : 'Éditer les disponibilités'}</button
			>{/if}
		{#if mode === 'availability' && single !== null && pattern && !loading}
			{#if administrator}
				<div
					class="kholle-hours"
					role="group"
					aria-label="Heures de khôlles par semaine"
					aria-busy={busy}
				>
					<span>Khôlles h/sem.</span>
					<label for="kholle-min-hours">Min</label>
					<input
						id="kholle-min-hours"
						class="input is-small"
						aria-label="Minimum (h/semaine)"
						type="number"
						min="0"
						max="2147483647"
						step="1"
						required
						readonly={!editing}
						disabled={!canEdit}
						bind:value={kholleMinHours}
					/>
					<label for="kholle-max-hours">Max</label>
					<input
						id="kholle-max-hours"
						class="input is-small"
						aria-label="Maximum (h/semaine)"
						type="number"
						min={kholleMinHours ?? 0}
						max="2147483647"
						step="1"
						required
						readonly={!editing}
						disabled={!canEdit}
						bind:value={kholleMaxHours}
					/>
				</div>
			{:else}
				<p class="kholle-hours">
					Khôlles h/sem. : {pattern.kholle_min_hours}–{pattern.kholle_max_hours}
				</p>
			{/if}
		{/if}
		<div class="toolbar-spacer"></div>
		{#if annual && mode === 'timetable'}<div class="week-navigation">
				<button
					aria-label="Semaine précédente"
					disabled={monday <= mondayOf(annual.settings.start)}
					onclick={() => navigate(-7)}>‹</button
				>
				<label class="week-label"
					>Semaine du<input
						type="date"
						aria-label="Date consultée"
						bind:value={date}
						min={annual.settings.start}
						max={annual.settings.end}
					/></label
				>
				<button
					aria-label="Semaine suivante"
					disabled={monday >= mondayOf(annual.settings.end)}
					onclick={() => navigate(7)}>›</button
				>
			</div>{/if}
		<button
			class="button is-small is-light"
			disabled={!annual || loading || !selectedIds.length}
			onclick={() => (hoursOpen = true)}>Heures</button
		>
		<button
			class="button is-small is-light"
			disabled={busy || loading || !selectedIds.length}
			onclick={() => {
				void refresh();
			}}>Actualiser</button
		>
	</header>
	<p class="publication-help">
		{mode === 'availability'
			? 'Semaine type sans dates, valable pour l’année scolaire.'
			: administrator
				? 'Séances enregistrées des calendriers actifs.'
				: 'Séances diffusées des enseignants sélectionnés.'}
		{selectedName ? ` ${selectedName}.` : ''}
		{#if mode === 'availability'}
			Hachures claires : tous les élèves de tous les agendas actifs ont cours simultanément, au
			moins une semaine dans l’année.{/if}
		{editing
			? ' Déplacez les plages ou redimensionnez leurs bordures ; chaque modification est enregistrée.'
			: ''}
	</p>
	{#if message}<p class="workspace-message" role="alert">{message}</p>{/if}
	{#if notice}<p class="workspace-success" role="status">{notice}</p>{/if}
	<div class="workspace-body">
		<aside
			class="resource-sidebar"
			class:sidebar-open={sidebarOpen}
			aria-label="Enseignants par matière"
		>
			<div class="sidebar-search">
				<label for="teacher-search" class="is-sr-only"
					>Rechercher un enseignant ou une matière</label
				><input
					id="teacher-search"
					class="input is-small"
					placeholder="Rechercher…"
					bind:value={search}
				/>
				<p class="help">
					Ctrl gauche + clic : sélection multiple. Un clic sur une matière sélectionne ses
					enseignants.
				</p>
			</div>
			<div class="teacher-tree">
				{#each folders as folder (folder.id)}<section>
						<button
							class="subject-folder"
							disabled={busy}
							aria-pressed={folder.teachers.every((teacher) => selectedIds.includes(teacher.id))}
							onclick={() =>
								select(
									folder.teachers.map((teacher) => teacher.id),
									ctrlLeft,
									true
								)}><span aria-hidden="true">▾</span> {folder.name}</button
						>
						{#each folder.teachers as teacher (teacher.id)}<button
								class="teacher-row"
								class:selected={selectedIds.includes(teacher.id)}
								disabled={busy}
								aria-pressed={selectedIds.includes(teacher.id)}
								onclick={() => select([teacher.id], ctrlLeft)}
								><span class="teacher-dot" style:background={teacherColor(teacher.id)}
								></span>{teacher.name}</button
							>{/each}
					</section>{/each}
				{#if !folders.length}<p class="p-3 muted" role="status">Aucun enseignant.</p>{/if}
			</div>
			{#if editing && canEdit}<div class="availability-actions">
					<button class="button is-small is-primary" onclick={() => openRange(null)}
						>Ajouter une plage</button
					>
					<button
						class="button is-small is-light"
						onclick={() => {
							void save(null);
						}}>Rétablir toutes les disponibilités</button
					>
					<button
						class="button is-small is-light"
						onclick={() => {
							void save([]);
						}}>Toute la semaine indisponible</button
					>
				</div>{/if}
		</aside>
		<div class="calendar-area" aria-busy={loading || busy}>
			{#if !annual}<div class="calendar-empty">
					<h2>Aucune année scolaire configurée</h2>
					<p>
						Créez une année scolaire dans « Salles et années scolaires » pour saisir les
						disponibilités.
					</p>
					{#if administrator}<a class="button is-primary mt-4" href={resolve('/timetable/settings')}
							>Configurer les règles</a
						>{/if}
				</div>
			{:else if loading}<div class="calendar-empty" role="status">Chargement…</div>
			{:else if !selectedIds.length}<div class="calendar-empty">
					Sélectionnez un enseignant ou une matière.
				</div>
			{:else if gridYear}<TimetableGrid
					years={[gridYear]}
					events={displayedEvents}
					{date}
					editable={editing && canEdit}
					dateless={mode === 'availability'}
					availabilityMode={mode === 'availability'}
					occupiedRanges={mode === 'availability' ? (board.occupied_ranges ?? []) : []}
					oncreate={createAt}
					onopen={(event) => {
						if (mode === 'availability') openRange(Number(event.series_id));
						else detail = event;
					}}
					onmove={() => {}}
					oncopy={() => {}}
					onpaste={() => {}}
					onrangechange={rangeChanged}
				/>{/if}
		</div>
	</div>
</div>

{#if editorOpen}<Modal
		title={rangeIndex === null ? 'Ajouter une disponibilité' : 'Modifier une disponibilité'}
		onclose={() => {
			if (!busy) editorOpen = false;
		}}
	>
		<form onsubmit={submitRange}>
			{#if rangeMessage}<p class="notification is-danger is-light" role="alert">
					{rangeMessage}
				</p>{/if}
			<div class="field">
				<label class="label" for="availability-day">Jour</label>
				<div class="select">
					<select id="availability-day" bind:value={weekday} disabled={busy}
						>{#each ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', ...(annual?.settings.saturday ? ['Samedi'] : [])] as day, index (day)}<option
								value={index}>{day}</option
							>{/each}</select
					>
				</div>
			</div>
			<div class="field">
				<label class="label" for="availability-start">Début</label><input
					id="availability-start"
					class="input"
					type="time"
					step="1"
					bind:value={rangeStart}
					required
					disabled={busy}
				/>
			</div>
			<div class="field">
				<label class="label" for="availability-end">Fin</label><input
					id="availability-end"
					class="input"
					type="time"
					step="1"
					bind:value={rangeEnd}
					required
					disabled={busy}
				/>
			</div>
			<p class="help mb-4">
				Plages de 08h00 à 19h00 en semaine et de 08h00 à 12h00 le samedi, sans pause imposée. Les
				plages qui se touchent ou se recouvrent sont réunies.
			</p>
			<div class="buttons">
				<button class="button is-primary" disabled={busy}>Enregistrer</button><button
					type="button"
					class="button is-light"
					disabled={busy}
					onclick={() => (editorOpen = false)}>Annuler</button
				>
			</div>
		</form>
	</Modal>{/if}
{#if hoursOpen && annual}<Modal
		title={`Heures — semaine du ${monday}`}
		onclose={() => (hoursOpen = false)}
		><TeacherHours
			events={weekEvents}
			sessionMinutes={annual.settings.session_minutes}
			subjects={data.catalog.subjects}
		/></Modal
	>{/if}
{#if detail}<Modal title={detail.title} onclose={() => (detail = null)}
		><p>{detail.teacher}</p>
		<p>
			{detail.kind.toUpperCase()} · {detail.start.slice(0, 10)} · {detail.start.slice(
				11,
				16
			)}–{detail.end.slice(11, 16)}
		</p>
		{#if detail.room}<p>Salle : {detail.room}</p>{/if}</Modal
	>{/if}

<style>
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
		flex-wrap: wrap;
	}
	.back {
		color: var(--color-ink);
		font-size: 1.4rem;
		padding: 0.3rem;
	}
	.workspace-name {
		min-width: 90px;
	}
	h1 {
		font-size: 1rem;
		font-weight: 700;
		line-height: 1.3;
	}
	.workspace-name span,
	.week-label {
		display: block;
		color: var(--color-muted);
		font-size: 0.73rem;
	}
	.toolbar-spacer {
		flex: 1;
	}
	.year-select {
		max-width: 130px;
		font-size: 0.8rem;
		border: var(--border-thin);
		color: inherit;
		background: var(--color-surface);
		border-radius: 5px;
		padding: 0.3rem;
	}
	.mode-buttons {
		margin: 0;
	}
	.kholle-hours {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		margin: 0;
		font-size: 0.75rem;
		white-space: nowrap;
		border-left: var(--border-thin);
		padding-left: 0.75rem;
		margin-left: 0.25rem;
	}
	.kholle-hours input {
		width: 3.5rem;
		height: 2.5em;
		min-height: 0;
		padding: 0.25em 0.5em;
		font-size: 0.75rem;
	}
	.week-navigation {
		display: flex;
		align-items: center;
		gap: 3px;
	}
	.week-navigation button {
		border: 0;
		background: none;
		color: inherit;
		cursor: pointer;
		padding: 0.2rem 0.5rem;
		font-size: 1.3rem;
	}
	.week-navigation button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.week-label input {
		display: block;
		width: 130px;
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
	.sidebar-search {
		padding: 1rem;
	}
	.teacher-tree {
		flex: 1;
		overflow-y: auto;
		padding: 0 0.6rem 1rem;
	}
	.teacher-tree button {
		border: 0;
		color: inherit;
		background: none;
		cursor: pointer;
		width: 100%;
		text-align: left;
		border-radius: 6px;
		padding: 0.55rem 0.65rem;
		font: inherit;
		font-size: 0.82rem;
	}
	.teacher-tree button:hover,
	.teacher-tree button.selected {
		background: var(--color-soft);
	}
	.teacher-tree button.selected {
		color: var(--color-primary);
	}
	.teacher-tree .subject-folder {
		font-weight: 700;
		margin-top: 0.4rem;
	}
	.teacher-tree .teacher-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding-left: 1.5rem;
	}
	.teacher-dot {
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 50%;
		flex: none;
	}
	.availability-actions {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.8rem;
		border-top: var(--border-thin);
	}
	.availability-actions button {
		white-space: normal;
		height: auto;
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
	.calendar-empty h2 {
		font-size: 1.2rem;
		color: var(--color-ink);
		margin-bottom: 0.5rem;
	}
	.workspace-message,
	.workspace-success {
		padding: 0.55rem 1rem;
		font-size: 0.85rem;
	}
	.workspace-message {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}
	.workspace-success {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.tree-toggle {
		display: none;
	}
	@media (max-width: 760px) {
		.tree-toggle {
			display: block;
		}
		.resource-sidebar {
			display: none;
			position: absolute;
			top: 0;
			bottom: 0;
			left: 0;
			z-index: 5;
			box-shadow: var(--shadow-panel);
		}
		.resource-sidebar.sidebar-open {
			display: flex;
		}
		.toolbar-spacer {
			display: none;
		}
	}
</style>
