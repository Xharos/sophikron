<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { beforeNavigate } from '$app/navigation';
	import Icon from './Icon.svelte';
	import SubjectTag from './SubjectTag.svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		kholleMinutes,
		kholleDuration,
		kholleLoad,
		khollePupilMinutes,
		type KholleState
	} from '#lib/kholle';
	let {
		calendarId,
		subjects,
		onsaved,
		ondirty,
		canWrite = true
	}: {
		calendarId: number;
		subjects: {
			id: number;
			name: string;
			color: string;
			icon?: import('#lib/lessons').LessonIcon;
		}[];
		onsaved: () => Promise<void>;
		ondirty: (value: boolean) => void;
		canWrite?: boolean;
	} = $props();
	let configuration = $state<KholleState | null>(null);
	const canEdit = $derived(canWrite && !configuration?.published);
	let start = $state('');
	let end = $state('');
	let values = $state<Record<number, string>>({});
	let busy = $state(true);
	let message = $state('');
	let saved = $state('');
	let editing = $state(true);
	const settingsKey = (settings: {
		start: string;
		end: string;
		subjects: { subject_id: number; minutes: number | null }[];
	}): string =>
		JSON.stringify([
			settings.start,
			settings.end,
			[...settings.subjects].sort((a, b) => a.subject_id - b.subject_id)
		]);
	const snapshot = $derived(JSON.stringify([start, end, values]));
	const dirty = $derived(configuration !== null && snapshot !== saved);
	$effect(() => {
		ondirty(dirty || busy);
	});
	onDestroy(() => {
		ondirty(false);
	});
	beforeNavigate((navigation) => {
		if (dirty && !window.confirm('Abandonner les modifications des volumes ?')) navigation.cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent): void {
		if (dirty) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	const selected = $derived(
		Object.entries(values).map(([id, value]) => ({ id: Number(id), minutes: kholleMinutes(value) }))
	);
	const weeks = $derived(
		configuration?.weeks.filter((week) => week.start >= start && week.end <= end && week.eligible)
			.length ?? 0
	);
	const load = $derived(
		kholleLoad(
			selected.map((item) => item.minutes ?? 0),
			configuration?.group_count ?? 0,
			weeks
		)
	);
	const valid = $derived(
		start <= end &&
			!!configuration?.weeks.some((week) => week.start === start) &&
			!!configuration?.weeks.some((week) => week.end === end) &&
			weeks > 0 &&
			selected.length > 0 &&
			selected.every((item) => item.minutes !== null) &&
			selected.every((item) => subjects.some((subject) => subject.id === item.id))
	);
	const maximum = $derived(Math.max(1, ...selected.map((item) => item.minutes ?? 0)));
	const decimal = (value: number): string =>
		value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
	const dateLabel = (value: string): string =>
		new Date(`${value}T12:00:00Z`).toLocaleDateString('fr-FR', { timeZone: 'UTC' });
	onMount(() => {
		void read();
	});
	async function read(): Promise<void> {
		busy = true;
		message = '';
		try {
			configuration = await timetableCommand<KholleState>(
				`calendars/${calendarId}/kholle/preview`,
				'POST',
				{}
			);
			start =
				configuration.settings?.start ??
				configuration.weeks.find((week) => week.eligible)?.start ??
				'';
			end =
				configuration.settings?.end ??
				configuration.weeks.findLast((week) => week.eligible)?.end ??
				'';
			values = Object.fromEntries(
				(configuration.settings?.subjects ?? []).map((item) => [
					item.subject_id,
					String(item.minutes / 60)
				])
			);
			saved = JSON.stringify([start, end, values]);
			editing = canEdit && configuration.settings === null;
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Chargement impossible.';
		} finally {
			busy = false;
		}
	}
	async function save(): Promise<void> {
		if (!configuration || !valid || !canEdit) return;
		const settings = {
			start,
			end,
			subjects: selected.map((item) => ({ subject_id: item.id, minutes: item.minutes }))
		};
		if (configuration.settings && settingsKey(settings) === settingsKey(configuration.settings)) {
			saved = snapshot;
			editing = false;
			return;
		}
		busy = true;
		message = '';
		try {
			await timetableCommand(`calendars/${calendarId}/kholle`, 'PUT', {
				expected_revision: configuration.revision,
				expected_year_revision: configuration.year_revision,
				settings
			});
			saved = snapshot;
			await read();
			await onsaved();
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Enregistrement impossible.';
		} finally {
			busy = false;
		}
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />
{#snippet volumeChart()}
	{#if configuration && selected.length}<figure class="volume-chart">
			<figcaption class="label">Volume par groupe · moyenne par élève</figcaption>
			{#each selected as item (item.id)}
				{@const subject = subjects.find((subject) => subject.id === item.id)}
				{@const pupilMinutes =
					item.minutes === null
						? null
						: khollePupilMinutes(item.minutes, weeks, configuration.group_size)}
				{#if item.minutes !== null && subject}
					<div class="chart-row" style:--subject-color={subject.color}>
						<div class="chart-heading">
							<SubjectTag subject={{ ...subject, icon: subject.icon ?? 'book' }} />
							<strong>{kholleDuration(item.minutes)}</strong>
						</div>
						<div
							class="bar-track"
							role="img"
							aria-label={`${subject.name} : ${kholleDuration(item.minutes)}`}
						>
							<div class="bar-fill" style:width={`${(item.minutes / maximum) * 100}%`}></div>
						</div>
						<p class="pupil-average">
							<strong>{pupilMinutes === null ? '—' : decimal(pupilMinutes)}</strong> min/élève/semaine
						</p>
					</div>
				{/if}
			{/each}
			<p class="help">
				Moyenne calculée pour des groupes de {configuration.group_size ?? '—'} élèves.
			</p>
		</figure>
	{/if}{/snippet}
<section aria-label="Volumes de khôlle" aria-busy={busy}>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if !configuration}
		<p role="status">
			{busy ? 'Chargement des réglages…' : 'Les réglages n’ont pas pu être chargés.'}
		</p>
		{#if !busy}<button class="button" onclick={read}>Réessayer</button>{/if}
	{:else if !editing}
		<div class="saved-period">
			<p>Du {dateLabel(start)} au {dateLabel(end)}</p>
			<small
				>{weeks} semaines · {configuration.group_count} groupes de {configuration.group_size ?? '—'} élèves</small
			>
		</div>
		{@render volumeChart()}
		<div class="saved-footer">
			<p>Total annuel par groupe <strong>{kholleDuration(load.perGroup)}</strong></p>
			<button
				class="button is-small is-light"
				disabled={busy || !canEdit}
				onclick={() => (editing = true)}>Modifier</button
			>
		</div>
	{:else}
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void save();
			}}
		>
			<fieldset disabled={busy || !canEdit}>
				<legend class="label">Période des khôlles</legend>
				<label class="label" for={`kholle-start-${calendarId}`}>Début · lundi matin</label>
				<div class="select is-fullwidth mb-4">
					<select id={`kholle-start-${calendarId}`} bind:value={start} required>
						<option value="" disabled>Choisir une semaine</option>
						{#each configuration.weeks as week (week.start)}<option value={week.start}
								>Semaine {week.number} · {dateLabel(week.start)}{week.eligible
									? ''
									: ' · exclue'}</option
							>{/each}
					</select>
				</div>
				<label class="label" for={`kholle-end-${calendarId}`}>Fin · vendredi soir</label>
				<div class="select is-fullwidth mb-4">
					<select id={`kholle-end-${calendarId}`} bind:value={end} required>
						<option value="" disabled>Choisir une semaine</option>
						{#each configuration.weeks as week (week.start)}<option value={week.end}
								>Semaine {week.number} · {dateLabel(week.end)}{week.eligible
									? ''
									: ' · exclue'}</option
							>{/each}
					</select>
				</div>
				<p class="notification is-info is-light" role="status">
					{weeks} semaine(s) disponible(s) · {configuration.group_count} groupe(s) de khôlle.
				</p>
				<p class="help mb-4">
					Semaines depuis la rentrée. Au moins 3 jours disponibles du lundi au vendredi, hors
					vacances de cet agenda.
				</p>
				{#if weeks === 0}<p class="notification is-warning is-light">
						Choisissez une période contenant au moins une semaine disponible.
					</p>{/if}
				{#if configuration.group_count === 0}<p class="notification is-warning is-light">
						Aucun groupe de khôlle défini dans cette promotion. Les réglages peuvent être
						enregistrés ; la charge de l’équipe sera calculée une fois les groupes créés.
					</p>{/if}
				<p class="label">Heures de khôlle par groupe et par matière sur la période</p>
				<p class="help mb-3">
					21,5 ou 21.5 = 21h30. Saisie à la minute près. Ces volumes définissent les séances à
					prévoir pour chaque groupe.
				</p>
				{#each selected.filter((item) => !subjects.some((subject) => subject.id === item.id)) as item (item.id)}
					<p class="notification is-warning">
						La matière {item.id} n’est plus disponible.
						<button
							type="button"
							class="button is-small"
							onclick={() => {
								delete values[item.id];
							}}>Retirer</button
						>
					</p>
				{/each}
				<div class="subject-table">
					<table>
						<thead><tr><th>Matière</th><th>Heures / groupe</th></tr></thead>
						<tbody>
							{#each subjects as subject (subject.id)}
								<tr class:chosen={subject.id in values} style:--subject-color={subject.color}>
									<td
										><div class="subject-choice">
											<button
												type="button"
												class="subject-icon"
												aria-label={subject.name}
												aria-pressed={subject.id in values}
												onclick={() => {
													if (subject.id in values) delete values[subject.id];
													else values[subject.id] = '';
												}}
											>
												<Icon name={subject.icon ?? 'book'} size={16} />
											</button><span>{subject.name}</span>
										</div></td
									>
									<td>
										{#if subject.id in values}
											<input
												class="input hours-input"
												aria-label={`Heures par groupe · ${subject.name}`}
												type="text"
												inputmode="decimal"
												bind:value={values[subject.id]}
												required
												aria-invalid={kholleMinutes(values[subject.id]) === null}
											/>
										{:else}<span class="muted">—</span>{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if !subjects.length}<p>Aucune matière disponible dans le catalogue.</p>{/if}
				{#if selected.length}
					{@render volumeChart()}
				{/if}
				<div class="team-summary" role="status">
					<p>
						{kholleDuration(load.perGroup)} par groupe × {configuration.group_count} groupes = {kholleDuration(
							load.total
						)} pour l’équipe sur la période.
					</p>
					<p class="is-size-5">
						<strong
							>{load.weekly === null ? '—' : decimal(load.weekly)} h de khôlle/semaine pour l’équipe pédagogique</strong
						>
					</p>
					{#if !valid}<p class="help">
							Complétez des réglages valides pour obtenir le calcul définitif.
						</p>{/if}
				</div>
				<p class="help">
					Les moyennes sont indicatives. Exemple : 10 min par élève et par semaine représentent,
					pour 3 élèves, 1 h de khôlle toutes les deux semaines.
				</p>
				<button class="button is-primary mt-4" disabled={busy || !valid}>Enregistrer</button>
			</fieldset>
		</form>
	{/if}
</section>

<style>
	.saved-period {
		margin-bottom: 1rem;
		font-size: 0.85rem;
		color: var(--color-ink);
	}
	.saved-period small {
		display: block;
		font-size: 0.72rem;
		color: var(--color-muted);
		margin-top: 0.2rem;
	}
	.saved-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-top: 0.8rem;
	}
	.saved-footer p {
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.saved-footer strong {
		margin-left: 0.4rem;
		color: var(--color-ink);
	}
	.subject-table {
		overflow-x: auto;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		margin-bottom: 1.5rem;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
		color: var(--color-ink);
		background: var(--color-surface);
	}
	th {
		text-align: left;
		font-size: 0.75rem;
		color: var(--color-muted);
		background: var(--color-paper);
		padding: 0.8rem 1rem;
	}
	td {
		padding: 0.8rem 1rem;
		vertical-align: middle;
		border-top: var(--border-thin);
	}
	tr.chosen {
		background: color-mix(in srgb, var(--subject-color) 7%, var(--color-surface));
	}
	.subject-choice {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		cursor: pointer;
	}
	.subject-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 2rem;
		height: 2rem;
		border-radius: 0.6rem;
		border: var(--border-thin);
		color: var(--color-muted);
		background: var(--color-surface);
		cursor: pointer;
	}
	.subject-icon[aria-pressed='true'] {
		color: var(--color-ink);
		background: color-mix(in srgb, var(--subject-color) 28%, var(--color-surface));
		border-color: var(--subject-color);
		box-shadow: inset 0 0 0 1px var(--subject-color);
	}
	.subject-icon:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
	.hours-input {
		width: 5rem;
		height: 2rem;
		min-height: 2rem;
		padding: 0.2rem 0.5rem;
		font-size: 0.85rem;
		max-width: 100%;
	}

	.volume-chart {
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		padding: 1.2rem;
		margin: 0 0 1.5rem;
		background: var(--color-paper);
		color: var(--color-ink);
	}
	.chart-row + .chart-row {
		margin-top: 1.2rem;
	}
	.chart-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.6rem;
		margin-bottom: 0.6rem;
	}
	.chart-heading strong {
		white-space: nowrap;
		font-size: 0.85rem;
	}
	.bar-track {
		height: 0.65rem;
		border-radius: 1rem;
		overflow: hidden;
		background: color-mix(in srgb, var(--subject-color) 12%, var(--color-surface));
	}
	.bar-fill {
		height: 100%;
		border-radius: inherit;
		background: var(--subject-color);
		transition: width 0.2s ease;
	}
	.pupil-average {
		text-align: right;
		font-size: 0.8rem;
		color: var(--color-muted);
		margin-top: 0.4rem;
	}
	.pupil-average strong {
		color: var(--color-ink);
	}
	.team-summary {
		padding: 1.2rem;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		color: var(--color-ink);
		background: var(--color-paper);
		margin-bottom: 1rem;
	}
	.team-summary strong {
		color: var(--color-ink);
	}
	@media (max-width: 480px) {
		td,
		th {
			padding: 0.65rem 0.5rem;
		}
		.hours-input {
			width: 5rem;
		}
		.chart-heading {
			flex-wrap: wrap;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.bar-fill {
			transition: none;
		}
	}
</style>
