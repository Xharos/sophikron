<script lang="ts">
	import { beforeNavigate, goto, invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { tick, untrack, type Snippet } from 'svelte';
	import type { PageData } from '../../routes/timetable/kholloscope/$types';
	import { timetableCommand } from '#lib/timetableClient';
	import {
		compareWishPeople,
		promotionPreferenceText,
		roomSelectionKey,
		kholloscopeStepStates,
		type KholloscopeWorkflow
	} from '#lib/kholleWishes';
	import SubjectTag from './SubjectTag.svelte';
	import RoleBadges from './RoleBadges.svelte';
	import KholleRoomSelection from './KholleRoomSelection.svelte';
	import type { GenerationView } from '#lib/kholloscopeGeneration';

	let {
		data,
		children,
		dirtyInputs = false,
		wishesReady = true,
		saveWishes,
		editorNotice = '',
		generation = null
	}: {
		data: PageData;
		children: Snippet;
		dirtyInputs?: boolean;
		wishesReady?: boolean;
		saveWishes?: () => Promise<boolean>;
		editorNotice?: string;
		generation?: GenerationView | null;
	} = $props();
	let selected = $state<Record<number, number[]>>(
		untrack(() =>
			Object.fromEntries(
				(data.workflow?.selected_rooms ?? []).map((item) => [item.subject_id, item.room_ids])
			)
		)
	);
	let busy = $state(false);
	let saving = $state(false);
	let serviceEditing = $state(untrack(() => !data.workflow?.validated.service));
	let preferences = $state<Record<number, boolean>>(
		untrack(() =>
			Object.fromEntries(
				(data.workflow?.teacher_preferences ?? []).map((item) => [
					item.user_id,
					item.prefer_own_promotion
				])
			)
		)
	);
	let savedPreferences = $state(untrack(() => JSON.stringify(preferences)));
	let savedRoomKey = $state(untrack(() => roomSelectionKey(selected)));
	let message = $state('');
	let notice = $state('');
	$effect(() => {
		if (data.tab) {
			message = '';
			notice = '';
		}
	});
	$effect(() => {
		if (dirtyInputs) notice = '';
	});
	let savedWorkflow = $state.raw<{
		source: KholloscopeWorkflow | null;
		value: KholloscopeWorkflow;
	} | null>(null);
	const workflow = $derived(
		savedWorkflow?.source === data.workflow ? savedWorkflow.value : data.workflow
	);
	let invalidatedGenerationSource = $state.raw<KholloscopeWorkflow | null | undefined>(undefined);
	const effectiveGeneration = $derived(
		invalidatedGenerationSource === data.workflow && generation?.run
			? { ...generation, run: { ...generation.run, stale: true } }
			: generation
	);
	const published = $derived(!!effectiveGeneration?.run?.result?.applied);
	const canPrepare = $derived(data.canWrite && !published);
	$effect(() => {
		const tab = data.tab;
		const rooms = data.workflow?.selected_rooms ?? [];
		const teacherPreferences = data.workflow?.teacher_preferences ?? [];
		if (tab !== 'service') {
			serviceEditing = !data.workflow?.validated.service;
			const savedSelection = Object.fromEntries(
				rooms.map((item) => [item.subject_id, item.room_ids])
			);
			selected = savedSelection;
			savedRoomKey = roomSelectionKey(savedSelection);
			const values = Object.fromEntries(
				teacherPreferences.map((item) => [item.user_id, item.prefer_own_promotion])
			);
			preferences = values;
			savedPreferences = JSON.stringify(values);
		}
	});
	const dirty = $derived(
		data.tab === 'service' &&
			(roomSelectionKey(selected) !== savedRoomKey ||
				JSON.stringify(preferences) !== savedPreferences)
	);
	const stepStates = $derived(
		kholloscopeStepStates(
			workflow,
			effectiveGeneration,
			data.tab,
			dirty ? 'service' : dirtyInputs ? data.tab : null
		)
	);
	function cancelService(): void {
		if (dirty && !window.confirm('Abandonner les modifications du service et des salles ?')) return;
		selected = Object.fromEntries(
			(workflow?.selected_rooms ?? []).map((item) => [item.subject_id, item.room_ids])
		);
		preferences = Object.fromEntries(
			(workflow?.teacher_preferences ?? []).map((item) => [item.user_id, item.prefer_own_promotion])
		);
		serviceEditing = false;
		message = notice = '';
	}
	beforeNavigate((navigation) => {
		if (saving || (dirty && !window.confirm('Abandonner les modifications des salles ?')))
			navigation.cancel();
	});
	function beforeUnload(event: BeforeUnloadEvent): void {
		if (dirty || saving) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	async function validate(): Promise<void> {
		if (
			!canPrepare ||
			data.tab === 'generation' ||
			data.tab === 'groups' ||
			data.tab === 'revision'
		)
			return;
		if (!workflow || busy || (dirtyInputs && data.tab !== 'wishes')) return;
		if (data.tab === 'wishes' && !wishesReady) return;
		const nextTab = { volumes: 'wishes', wishes: 'service', service: 'generation' }[data.tab];
		if (data.tab === 'service' && !serviceEditing && workflow.validated.service && !dirty) {
			await goto(
				resolve(`/timetable/kholloscope?school_year=${workflow.school_year}&tab=generation`)
			);
			return;
		}
		busy = true;
		saving = true;
		message = notice = '';
		try {
			if (data.tab === 'wishes' && saveWishes) {
				if (!(await saveWishes())) return;
				await tick();
			}
			const result = await timetableCommand<KholloscopeWorkflow>(
				`kholloscope/${workflow.school_year}/workflow`,
				'PUT',
				{
					step: data.tab,
					expected_revision: workflow.revision,
					teacher_preferences:
						data.tab === 'service'
							? (workflow.teacher_preferences ?? []).map((item) => ({
									user_id: item.user_id,
									prefer_own_promotion: preferences[item.user_id] ?? true
								}))
							: null,
					rooms:
						data.tab === 'service'
							? workflow.subjects.map((subject) => ({
									subject_id: subject.id,
									room_ids: selected[subject.id] ?? []
								}))
							: []
				}
			);
			if (result.revision !== workflow.revision) invalidatedGenerationSource = data.workflow;
			savedWorkflow = { source: data.workflow, value: result };
			saving = false;
			if (data.tab === 'service') {
				selected = Object.fromEntries(
					result.selected_rooms.map((item) => [item.subject_id, item.room_ids])
				);
				savedRoomKey = roomSelectionKey(selected);
				preferences = Object.fromEntries(
					(result.teacher_preferences ?? []).map((item) => [
						item.user_id,
						item.prefer_own_promotion
					])
				);
				savedPreferences = JSON.stringify(preferences);
				serviceEditing = false;
			}
			notice = 'Enregistrement effectué.';
			try {
				await invalidateAll();
				await goto(
					resolve(`/timetable/kholloscope?school_year=${result.school_year}&tab=${nextTab}`)
				);
			} catch {
				message = 'Enregistrement effectué. Ouvrez l’étape suivante depuis le menu.';
			}
		} catch (cause) {
			message = cause instanceof Error ? cause.message : 'Validation impossible.';
		} finally {
			busy = false;
			saving = false;
		}
	}
</script>

<svelte:window onbeforeunload={beforeUnload} />
<div class="kholloscope-workspace">
	<aside class="preparation-sidebar">
		<a class="sidebar-title" href={resolve('/timetable')}
			>Kholloscope<small>Préparation annuelle</small></a
		>
		<form method="GET" class="year-picker">
			<input type="hidden" name="tab" value={data.tab} />
			<label class="label" for="kholloscope-year">Année scolaire</label>
			<div class="select is-fullwidth">
				<select
					id="kholloscope-year"
					name="school_year"
					value={data.overview.school_year ?? ''}
					onchange={(event) => event.currentTarget.form?.requestSubmit()}
					disabled={busy}
				>
					{#if !data.overview.years.length}<option value="">Aucune année scolaire</option>{/if}
					{#each data.overview.years as year (year)}<option value={year}>{year}/{year + 1}</option
						>{/each}
				</select>
			</div>
		</form>
		<nav aria-label="Étapes de création du kholloscope">
			{#each stepStates as step, index (step.id)}
				{@const validated = step.validated}
				{@const current = step.current}
				{@const review = step.review}
				{@const pending = step.pending}
				{@const status = validated
					? 'Validée'
					: review
						? 'À reconfirmer'
						: pending
							? 'En cours'
							: 'Non faite'}
				<a
					class="step"
					class:done={validated}
					class:current={!validated && (review || pending)}
					class:locked={!step.available}
					href={step.available
						? resolve(
								`/timetable/kholloscope?school_year=${data.overview.school_year}&tab=${step.id}`
							)
						: undefined}
					aria-disabled={!step.available}
					role={!step.available ? 'link' : undefined}
					aria-current={current ? 'page' : undefined}
				>
					<span class="step-number">{validated ? '✓' : index + 1}</span><span
						>{step.label}<small>{status}{!step.available ? ' · verrouillée' : ''}</small></span
					>
				</a>
			{/each}
		</nav>
	</aside>
	<div class="preparation-content">
		{#if published}
			<p class="notification is-info is-light" role="status">
				Ce kholloscope est publié dans les agendas. La préparation est en lecture seule.
				<a
					href={resolve(
						`/timetable/kholloscope?school_year=${data.overview.school_year}&tab=revision`
					)}>Ouvrir une révision</a
				>
				pour modifier le planning publié.
				{#each data.generation?.pending_publications ?? [] as publication (publication.id)}
					<br />Révision publiée : prise d’effet le {publication.effective_on}.
				{/each}
			</p>
		{/if}
		{#if workflow?.errors.length}<div class="notification is-danger is-light" role="alert">
				{#each workflow.errors as problem (problem)}<p>{problem}</p>{/each}
			</div>{/if}
		{#if data.accessError}<p class="notification is-danger is-light" role="alert">
				{data.accessError}
			</p>{/if}
		{@render children()}
		{#if data.tab !== 'generation' && data.tab !== 'groups' && data.tab !== 'revision' && !published && workflow?.review[data.tab] && workflow.conflicts[data.tab].length}<div
				class="notification is-warning is-light"
				role="status"
			>
				{#each workflow.conflicts[data.tab] as conflict (conflict)}<p>{conflict}</p>{/each}
			</div>{/if}
		{#if data.tab === 'service' && !data.accessError && workflow}
			<section class="service-panel">
				<div class="service-heading">
					{#if canPrepare && !serviceEditing}<button
							class="button is-small is-light"
							disabled={busy}
							onclick={() => {
								serviceEditing = true;
								message = notice = '';
							}}>Modifier</button
						>{/if}
				</div>
				<p class="help mb-5">
					Sélectionnez au moins une salle par matière. Une salle peut servir à plusieurs matières ;
					les réservations seront vérifiées lors du placement.
				</p>
				{#if !workflow.rooms.length}<p class="notification is-warning is-light">
						Aucune salle active. Créez des salles dans <a href={resolve('/timetable/settings')}
							>les réglages des salles</a
						>.
					</p>{/if}
				{#each workflow.subjects as subject (subject.id)}
					<article class="room-subject" style:--subject-color={subject.color}>
						<header>
							<SubjectTag {subject} /><span
								>{(selected[subject.id] ?? []).length} salle(s) sélectionnée(s)</span
							>
						</header>
						<KholleRoomSelection
							{subject}
							rooms={workflow.rooms}
							selected={selected[subject.id] ?? []}
							disabled={busy || !serviceEditing || !canPrepare}
							onselected={(ids) => {
								selected[subject.id] = ids;
								notice = '';
							}}
						/>
						<div class="table-container">
							<table class="table is-fullwidth">
								<caption>Répartition automatique des séances</caption><thead
									><tr
										><th>Intervenant</th><th>Rôle</th><th>Préférence de promotion</th><th
											>{(subject.cycle_weeks ?? 2) === 2
												? 'Semaine A'
												: `Cycle de ${subject.cycle_weeks} semaines`}</th
										><th>{(subject.cycle_weeks ?? 2) === 2 ? 'Semaine B' : 'Moyenne / semaine'}</th
										></tr
									></thead
								><tbody
									>{#each subject.staff
										.filter((person) => (person.sessions ?? 0) > 0)
										.sort(compareWishPeople) as person (person.id)}
										{@const preference = workflow.teacher_preferences?.find(
											(item) => item.user_id === person.id
										)}<tr
											><th scope="row">{person.name}</th><td><RoleBadges roles={person.roles} /></td
											><td>
												<label
													class="promotion-preference"
													class:ineffective={!preference?.effective}
													><input
														type="checkbox"
														role="switch"
														aria-label={`Priorité à ${preference && preference.promotion_ids.length > 1 ? 'ses promotions' : 'sa promotion'} — ${person.name} — ${subject.name}`}
														checked={preferences[person.id] ?? true}
														disabled={busy ||
															!serviceEditing ||
															!canPrepare ||
															!preference?.effective}
														onchange={(event) => {
															preferences[person.id] = event.currentTarget.checked;
															notice = '';
														}}
													/><span
														>{promotionPreferenceText(
															preference?.promotion_ids.length ?? 0,
															preferences[person.id] === false
														)}</span
													></label
												>
											</td><td
												>{(subject.cycle_weeks ?? 2) === 2
													? (person.sessions_a ?? '—')
													: (person.sessions ?? '—')}</td
											><td
												>{(subject.cycle_weeks ?? 2) === 2
													? (person.sessions_b ?? '—')
													: ((person.sessions ?? 0) / (subject.cycle_weeks ?? 2)).toLocaleString(
															'fr-FR',
															{ maximumFractionDigits: 2 }
														)}</td
											></tr
										>{/each}</tbody
								>
							</table>
						</div>
					</article>
				{/each}
			</section>
		{/if}
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		{#if notice || editorNotice}<p class="notification is-success is-light" role="status">
				{notice || editorNotice}
			</p>{/if}
		{#if canPrepare && data.tab !== 'revision' && data.tab !== 'generation' && data.tab !== 'groups' && !data.accessError && workflow && !workflow.errors.length}
			{#if data.tab === 'wishes' && workflow.wish_errors.length}<div
					class="notification is-warning is-light"
				>
					{#each workflow.wish_errors as problem (problem)}<p>{problem}</p>{/each}
				</div>{/if}
			<div class="step-actions">
				<p>
					{dirtyInputs
						? 'Enregistrez les modifications avant de valider cette étape.'
						: 'La validation conserve votre progression pour cette année.'}
				</p>
				<div class="buttons mb-0">
					{#if data.tab === 'service' && serviceEditing}<button
							class="button is-light"
							disabled={busy}
							onclick={cancelService}>Annuler</button
						>{/if}
					<button
						class="button is-primary"
						class:is-loading={busy}
						disabled={busy ||
							(dirtyInputs && data.tab !== 'wishes') ||
							(data.tab === 'wishes' &&
								(!wishesReady || (!dirtyInputs && !!workflow.wish_errors.length))) ||
							(data.tab === 'service' &&
								workflow.subjects.some((subject) => !selected[subject.id]?.length))}
						onclick={validate}>Enregistrer et continuer</button
					>
				</div>
			</div>
		{/if}
	</div>
</div>

<style>
	.kholloscope-workspace {
		display: grid;
		grid-template-columns: 260px minmax(0, 1fr);
		min-height: 75vh;
		max-width: 1600px;
		margin: auto;
	}
	.preparation-sidebar {
		padding: 2rem 1.2rem;
		border-right: var(--border-thin);
		background: var(--color-paper);
		position: sticky;
		top: 0;
		height: fit-content;
	}
	.sidebar-title {
		display: block;
		color: var(--color-ink);
		font-size: 1.3rem;
		font-weight: 700;
		margin-bottom: 1.5rem;
	}
	.sidebar-title small,
	.step small {
		display: block;
		font-size: 0.75rem;
		font-weight: 400;
		margin-top: 0.25rem;
	}
	.year-picker {
		margin-bottom: 2rem;
	}
	.step {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 1rem 0.65rem;
		margin: 0.5rem 0;
		border-radius: 8px;
		color: var(--color-danger);
		background: var(--color-danger-soft);
		font-size: 0.85rem;
		font-weight: 600;
	}
	.step.done {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.step.current {
		color: #9a4b00;
		background: #fff0d8;
	}
	.step[aria-current='page'] {
		outline: 2px solid currentColor;
		outline-offset: 2px;
	}
	.step.locked {
		cursor: not-allowed;
	}
	.step-number {
		border: 1px solid currentColor;
		border-radius: 50%;
		width: 1.7rem;
		height: 1.7rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
	}
	.preparation-content :global(.step-actions p) {
		color: var(--color-muted);
		font-size: 0.8rem;
		line-height: 1.6;
	}
	.preparation-content {
		padding: 1.5rem 2rem;
		min-width: 0;
	}
	.service-panel {
		margin: 1rem 0 2rem;
	}
	.service-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}
	.room-subject {
		border: var(--border-thin);
		border-top: 3px solid var(--subject-color);
		border-radius: var(--radius-panel);
		padding: 1.25rem;
		margin-bottom: 1.25rem;
	}
	.room-subject header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		font-size: 0.8rem;
		color: var(--color-muted);
	}
	.promotion-preference {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.8rem;
		cursor: pointer;
	}
	.promotion-preference input {
		appearance: none;
		width: 2.5rem;
		height: 1.4rem;
		border-radius: 1rem;
		background: var(--color-border);
		position: relative;
		flex: none;
		cursor: pointer;
	}
	.promotion-preference input::after {
		content: '';
		position: absolute;
		width: 1rem;
		height: 1rem;
		left: 0.2rem;
		top: 0.2rem;
		border-radius: 50%;
		background: white;
		transition: transform 0.15s;
	}
	.promotion-preference input:checked {
		background: var(--color-primary);
	}
	.promotion-preference input:checked::after {
		transform: translateX(1.1rem);
	}
	.promotion-preference input:focus-visible {
		outline: 2px solid var(--color-primary);
		outline-offset: 3px;
	}
	.promotion-preference.ineffective {
		opacity: 0.6;
		cursor: default;
	}
	.table {
		font-size: 0.85rem;
	}
	caption {
		text-align: left;
		color: var(--color-muted);
		padding: 0.75rem 0;
	}
	.preparation-content :global(.step-actions) {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		padding: 1.25rem;
		border: var(--border-thin);
		border-radius: var(--radius-panel);
		margin: 1rem 0;
	}
	@media (max-width: 850px) {
		.kholloscope-workspace {
			grid-template-columns: 1fr;
		}
		.preparation-sidebar {
			position: static;
			border-right: 0;
			border-bottom: var(--border-thin);
			padding: 1.25rem;
		}
		nav {
			display: flex;
			gap: 0.6rem;
			flex-wrap: wrap;
		}
		.step {
			flex: 1 1 180px;
		}
		.preparation-content {
			padding: 1rem;
		}
	}
</style>
