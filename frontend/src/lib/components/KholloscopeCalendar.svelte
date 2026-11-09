<script lang="ts">
	import { untrack } from 'svelte';
	import TimetableGrid from './TimetableGrid.svelte';
	import Modal from './Modal.svelte';
	import {
		mondayOf,
		shiftTimetableDate,
		type TimetableCatalog,
		type TimetableEvent,
		type TimetableYear
	} from '#lib/timetable';
	import {
		matchesSession,
		type GeneratedSession,
		type KholloscopeCalendarView
	} from '#lib/kholloscopeGeneration';
	let {
		view,
		catalog,
		sessions,
		onedit,
		showChanges = true
	}: {
		view: KholloscopeCalendarView;
		catalog: TimetableCatalog;
		sessions: GeneratedSession[];
		onedit?: (session: GeneratedSession) => void;
		showChanges?: boolean;
	} = $props();
	const result = $derived(view.run?.result);
	let calendar = $state(0);
	let teacher = $state(0),
		subject = $state(0),
		room = $state(0),
		group = $state(0);
	const filters = $derived({ calendar, teacher, subject, room, group });
	const resources = $derived(sessions);
	const groupNumbers = $derived(
		[
			...new Set(
				sessions
					.filter((s) => !calendar || s.calendar_id === calendar)
					.flatMap((s) => (s.group === undefined ? [] : [s.group]))
			)
		].sort((a, b) => a - b)
	);
	let day = $state(untrack(() => view.run?.result?.reference ?? catalog.today));
	let inspected = $state<TimetableEvent | null>(null);
	const calendars = $derived(
		catalog.calendars.filter(
			(c) => !c.is_archived && result?.quotas.some((q) => q.calendar_id === c.id)
		)
	);
	const filtered = $derived(sessions.filter((s) => matchesSession(s, filters)));
	const reference = $derived(result?.reference ?? day);
	const displayedDay = $derived(day || reference);
	const years = $derived.by(() => {
		const items = (view.run?.calendars ?? []).filter(
			(y) => !calendar || y.calendar_id === calendar
		);
		if (items.length <= 1) return items;
		return [
			{
				...items[0],
				settings: {
					...items[0].settings,
					day_start: Math.min(...items.map((y) => y.settings.day_start)),
					day_end: Math.max(...items.map((y) => y.settings.day_end)),
					saturday: items.some((y) => y.settings.saturday),
					breaks: [],
					holidays: [],
					lunch_start: 0,
					lunch_end: 0
				}
			} satisfies TimetableYear
		];
	});
	const events = $derived(
		filtered.map((s) => {
			const subject = catalog.subjects.find((v) => v.id === s.subject_id);
			return {
				id: s.id,
				series_id: s.id,
				source_date: s.day,
				start: `${s.day}T${clock(s.start)}`,
				end: `${s.day}T${clock(s.end)}`,
				start_slot: 0,
				duration_slots: 2,
				start_time: s.start,
				end_time: s.end,
				subject_id: s.subject_id,
				teacher_id: s.teacher_id,
				room_id: s.room_id,
				kind: 'kholle',
				title: subject?.name ?? 'Khôlle',
				color: subject?.color ?? '#808080',
				teacher: catalog.teachers.find((v) => v.id === s.teacher_id)?.name ?? '',
				room: catalog.rooms.find((v) => v.id === s.room_id)?.name ?? '',
				calendar_id: s.calendar_id,
				promotion_id: null,
				year_id: s.calendar_id,
				calendar_label: catalog.calendars.find((v) => v.id === s.calendar_id)?.name ?? '',
				audience_label: s.group ? `Groupe ${s.group}` : 'Proposition',
				target_kind: s.group ? 'kholles' : 'promotion',
				target_number: s.group ?? null
			} satisfies TimetableEvent;
		})
	);
	const changes = $derived(
		sessions
			.filter(
				(s) =>
					(s.original_day && s.original_day !== s.day) ||
					(s.original_start !== undefined && s.original_start !== s.start)
			)
			.filter((s) => matchesSession(s, filters))
	);
	function clock(seconds: number): string {
		return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
	}
	function open(event: TimetableEvent): void {
		const session = sessions.find((s) => s.id === event.id);
		if (onedit && session) onedit(session);
		else inspected = event;
	}
	function reason(session: GeneratedSession): string {
		const cfg = view.run?.calendars?.find((y) => y.calendar_id === session.calendar_id)?.settings;
		const holiday = cfg?.holidays.find(
			(h) => h.start <= (session.original_day ?? '') && (session.original_day ?? '') <= h.end
		);
		return holiday
			? `Fermeture : ${holiday.name}`
			: 'Adaptation aux contraintes de disponibilité, de salle ou de groupe';
	}
	function dateLabel(value: string): string {
		return new Intl.DateTimeFormat('fr-FR', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			timeZone: 'UTC'
		}).format(new Date(value + 'T12:00:00Z'));
	}
</script>

<section aria-label="Calendrier des propositions">
	<div class="calendar-toolbar workspace-panel">
		<h3 class="title is-5 mb-0">Calendrier annuel</h3>
		<div class="filters">
			<label class="label"
				>Promotion<select class="input" aria-label="Promotion" bind:value={calendar}
					><option value={0}>Toutes les promotions</option>{#each calendars as c (c.id)}<option
							value={c.id}>{c.name}</option
						>{/each}</select
				></label
			>
			<label class="label"
				>Intervenant<select class="input" aria-label="Intervenant" bind:value={teacher}
					><option value={0}>Tous les intervenants</option
					>{#each catalog.teachers.filter( (t) => resources.some((s) => s.teacher_id === t.id) ) as t (t.id)}<option
							value={t.id}>{t.name}</option
						>{/each}</select
				></label
			>
			<label class="label"
				>Matière<select class="input" aria-label="Matière" bind:value={subject}
					><option value={0}>Toutes les matières</option
					>{#each catalog.subjects.filter( (m) => resources.some((s) => s.subject_id === m.id) ) as m (m.id)}<option
							value={m.id}>{m.name}</option
						>{/each}</select
				></label
			>
			<label class="label"
				>Salle<select class="input" aria-label="Salle" bind:value={room}
					><option value={0}>Toutes les salles</option
					>{#each catalog.rooms.filter( (r) => resources.some((s) => s.room_id === r.id) ) as r (r.id)}<option
							value={r.id}>{r.name}</option
						>{/each}</select
				></label
			>
			{#if groupNumbers.length}<label class="label"
					>Groupe<select class="input" aria-label="Groupe" bind:value={group}
						><option value={0}>Tous les groupes</option>{#each groupNumbers as g (g)}<option
								value={g}>Groupe {g}</option
							>{/each}</select
					></label
				>{/if}
		</div>
		<button
			class="button is-small is-light"
			onclick={() => {
				calendar = teacher = subject = room = group = 0;
			}}>Réinitialiser les filtres</button
		>
	</div>
	<div class="week-navigation" role="group" aria-label="Semaine affichée">
		<button
			class="button"
			onclick={() => (day = shiftTimetableDate(mondayOf(day || reference), -7))}
			>Semaine précédente</button
		>
		<label class="label"
			>Date affichée<input class="input" type="date" bind:value={day} required /></label
		>
		<button class="button" onclick={() => (day = shiftTimetableDate(mondayOf(day || reference), 7))}
			>Semaine suivante</button
		>
	</div>
	{#if years.length}<TimetableGrid
			{years}
			{events}
			date={displayedDay}
			editable={false}
			onopen={open}
			oncreate={() => {}}
			onmove={() => {}}
			oncopy={() => {}}
			onpaste={() => {}}
		/>{:else}<p class="notification is-warning is-light">
			Rechargez ou régénérez pour afficher les paramètres du calendrier.
		</p>{/if}
	{#if !events.some((e) => mondayOf(e.source_date) === mondayOf(displayedDay))}<p role="status">
			Aucune khôlle cette semaine.
		</p>{/if}
	{#if showChanges}<div class="changes-panel workspace-panel mt-5">
			<h3 class="title is-5">
				Jours fériés et changements <span class="tag is-light">{changes.length}</span>
			</h3>
			<p class="help mb-4">
				Déplacements par rapport au cycle de référence, sur toute l’année et selon les filtres
				sélectionnés. Le motif générique ne précise pas la contrainte à l’origine du déplacement.
			</p>
			{#if !changes.length}<p role="status">Aucun déplacement pour cette sélection.</p>{:else}
				<div class="table-container">
					<table class="table is-fullwidth is-hoverable">
						<caption class="is-sr-only">Séances déplacées : créneau prévu et créneau retenu</caption
						>
						<thead
							><tr
								><th scope="col">Promotion / matière</th><th scope="col">Créneau prévu</th><th
									scope="col">Créneau retenu</th
								><th scope="col">Affectation</th><th scope="col">Motif</th></tr
							></thead
						>
						<tbody
							>{#each [...changes].sort((a, b) => a.day.localeCompare(b.day) || a.start - b.start) as s (s.id)}<tr
								>
									<th scope="row"
										>{catalog.calendars.find((c) => c.id === s.calendar_id)?.name}<small
											>{catalog.subjects.find((m) => m.id === s.subject_id)?.name}</small
										></th
									>
									<td class="date-cell"
										>{dateLabel(s.original_day ?? s.day)}<small
											>{clock(s.original_start ?? s.start)}</small
										></td
									>
									<td class="date-cell"
										><strong>{dateLabel(s.day)}</strong><small>{clock(s.start)}</small></td
									>
									<td
										>{catalog.teachers.find((t) => t.id === s.teacher_id)?.name}<small
											>{catalog.rooms.find((r) => r.id === s.room_id)?.name}{s.group
												? ' · Groupe ' + s.group
												: ''}</small
										></td
									>
									<td>{reason(s)}</td>
								</tr>{/each}</tbody
						>
					</table>
				</div>{/if}
		</div>{/if}
</section>
{#if inspected}<Modal title={inspected.title} busy={false} onclose={() => (inspected = null)}
		><p>{inspected.calendar_label} · {inspected.audience_label}</p>
		<p>{inspected.teacher} · {inspected.room}</p>
		<p>{inspected.source_date} · {inspected.start.slice(11)} – {inspected.end.slice(11)}</p></Modal
	>{/if}

<style>
	.calendar-toolbar {
		display: grid;
		gap: 1.25rem;
		margin-bottom: 1.5rem;
	}
	.week-navigation {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(10rem, 12rem) minmax(0, 1fr);
		justify-content: center;
		align-items: center;
		gap: 0.75rem;
	}
	.filters {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 13rem), 1fr));
		gap: 1rem;
	}
	.label {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin: 0;
		min-width: 0;
	}
	.input {
		width: 100%;
	}
	.calendar-toolbar > button {
		justify-self: start;
	}
	.week-navigation {
		margin: 0 auto 1.5rem;
		max-width: 44rem;
		width: 100%;
		align-items: end;
	}
	.week-navigation .label {
		text-align: center;
		min-width: 0;
	}
	.week-navigation .input {
		min-width: 0;
		max-width: 100%;
	}
	.week-navigation .button {
		min-width: 0;
		white-space: normal;
		height: auto;
		min-height: 2.5rem;
	}
	@media (max-width: 650px) {
		.week-navigation {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		}
		.week-navigation .label {
			grid-column: 1 / -1;
			grid-row: 1;
			width: min(100%, 16rem);
			justify-self: center;
		}
	}
	.changes-panel {
		min-width: 0;
	}
	.table {
		font-size: 0.9rem;
	}
	.table th,
	.table td {
		padding: 0.9rem;
		vertical-align: top;
	}
	small {
		display: block;
		margin-top: 0.3rem;
		color: var(--color-muted);
		font-weight: normal;
	}
	.date-cell {
		white-space: nowrap;
	}
</style>
