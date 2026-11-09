<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { beforeNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import Modal from './Modal.svelte';
	import KholloscopeCalendar from './KholloscopeCalendar.svelte';
	import { timetableCommand } from '#lib/timetableClient';
	import { timetableClock, type TimetableCatalog } from '#lib/timetable';
	import {
		defaultGenerationRules,
		generationTimeStages,
		generationTimeTotal,
		colloscopeRows,
		type GeneratedSession,
		type GenerationGroups,
		type GenerationRules,
		type GenerationView,
		type RotationMode
	} from '#lib/kholloscopeGeneration';
	let {
		year,
		initial,
		catalog,
		mode,
		onupdate,
		canWrite = true,
		ondirty
	}: {
		year: number;
		initial: GenerationView;
		catalog: TimetableCatalog;
		mode: 'generation' | 'groups';
		onupdate: (value: GenerationView) => void;
		canWrite?: boolean;
		ondirty?: (value: boolean) => void;
	} = $props();
	let view = $state<GenerationView>(untrack(() => initial));
	let rules = $state<GenerationRules>(
		untrack(() => {
			const saved = { ...defaultGenerationRules, ...initial.run?.rules };
			return {
				rounding: saved.rounding,
				teacher_lunch: saved.teacher_lunch,
				teacher_lunch_minutes: saved.teacher_lunch_minutes,
				recovery_weeks: saved.recovery_weeks,
				max_per_day: saved.max_per_day,
				time_limit: saved.time_limit,
				preserve_locks: true,
				optimize: true,
				time_stability_percent: saved.time_stability_percent,
				time_weekly_percent: saved.time_weekly_percent,
				time_rotation_percent: saved.time_rotation_percent,
				time_annual_percent: saved.time_annual_percent
			};
		})
	);
	let groups = $state<GenerationGroups | null>(null);
	let rotation = $state<RotationMode>(
		untrack(
			() =>
				initial.run?.result?.assignment_mode ??
				(initial.run?.result?.mappings.length ? 'fixed' : 'cycle')
		)
	);
	let removal = $state<0 | 1 | 2>(0);
	let removalText = $state('');
	let removalVersion = $state({ revision: '', source: '' });
	let busy = $state(false),
		message = $state(''),
		notice = $state('');
	let assigning = $state(false);
	let refreshVersion = 0;
	let groupsVersion = 0;
	let editing = $state<GeneratedSession | null>(null);
	let editDay = $state(''),
		editTime = $state(''),
		editRoom = $state(0),
		locked = $state(true);
	let confirmApply = $state(false);
	let logElement = $state<HTMLPreElement | null>(null);
	const logText = $derived(view.run?.logs.join('\n') ?? '');
	$effect(() => {
		const content = logText;
		const element = logElement;
		if (element && content) {
			void tick().then(() => {
				if (element.isConnected) element.scrollTop = element.scrollHeight;
			});
		}
	});
	const result = $derived(view.run?.result);
	const assigned = $derived(groups?.assigned_sessions ?? []);
	const assignmentTables = $derived(
		(groups?.calendars ?? []).map((calendar) => {
			const sessions = assigned.filter((s) => s.calendar_id === calendar.id);
			return {
				...calendar,
				subjects: catalog.subjects
					.filter((subject) => sessions.some((s) => s.subject_id === subject.id))
					.map((subject) => ({
						...subject,
						...colloscopeRows(
							sessions.filter((s) => s.subject_id === subject.id),
							Object.keys(
								view.run?.calendars?.find((c) => c.calendar_id === calendar.id)?.weeks ?? {}
							)
						)
					}))
			};
		})
	);
	const savedRotation = $derived(groups?.mode ?? result?.assignment_mode ?? 'fixed');
	const rotationLabels = {
		fixed: 'Groupes fixes',
		weekly: 'Décalage +1 par semaine de khôlle',
		cycle: 'Décalage +1 par cycle de référence'
	};
	let selectedAssignment = $state<GeneratedSession | null>(null);
	const weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
	const active = $derived(['queued', 'running'].includes(view.run?.status ?? ''));
	const canEdit = $derived(
		canWrite &&
			view.run?.status === 'completed' &&
			!view.run.stale &&
			!result?.applied &&
			!result?.withdrawn
	);
	const dirty = $derived(
		mode === 'groups' &&
			!!result?.mappings.length &&
			rotation !== (result.assignment_mode ?? 'fixed')
	);
	const rulesChanged = $derived.by(() => {
		const keys = Object.keys(defaultGenerationRules) as (keyof GenerationRules)[];
		return keys.some((key) => rules[key] !== (view.run?.rules[key] ?? defaultGenerationRules[key]));
	});
	$effect(() => {
		ondirty?.(canEdit && !active && (mode === 'generation' ? rulesChanged : dirty));
	});
	const statuses: Record<string, string> = {
		queued: 'En attente',
		running: 'Calcul en cours',
		completed: 'Proposition complète',
		infeasible: 'Contraintes incompatibles',
		timeout: 'Délai atteint — aucune conclusion d’impossibilité',
		cancelled: 'Calcul annulé',
		failed: 'Calcul interrompu'
	};
	const clock = (seconds: number): string =>
		`${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
	const name = (id: number): string =>
		catalog.calendars.find((c) => c.id === id)?.name ?? String(id);
	async function read<T>(kind: string): Promise<T> {
		const response = await fetch(
			resolve(`/timetable/kholloscope/data?school_year=${year}&kind=${kind}`)
		);
		const body = await response.json();
		if (!response.ok) throw new Error(body.message ?? 'Chargement impossible.');
		return body as T;
	}
	async function refresh(): Promise<void> {
		const version = ++refreshVersion;
		const next = await read<GenerationView>('generation');
		if (version === refreshVersion) {
			view = next;
			onupdate(view);
		}
	}
	async function readGroups(): Promise<void> {
		const version = ++groupsVersion;
		const next = await read<GenerationGroups>('groups');
		if (version === groupsVersion) groups = next;
	}
	onMount(() => {
		let stopped = false;
		let refreshing = false;
		async function poll(): Promise<void> {
			if (refreshing || stopped || busy) return;
			refreshing = true;
			try {
				await refresh();
			} catch (error) {
				message = error instanceof Error ? error.message : 'Suivi indisponible.';
			} finally {
				refreshing = false;
			}
		}
		if (mode === 'groups')
			void readGroups().catch((error) => {
				message = error instanceof Error ? error.message : 'Chargement impossible.';
			});
		const timer = setInterval(() => {
			if (active) void poll();
		}, 1000);
		void poll();
		return () => {
			stopped = true;
			clearInterval(timer);
			ondirty?.(false);
		};
	});
	beforeNavigate((nav) => {
		if (busy || (dirty && !window.confirm('Abandonner les modifications des groupes ?')))
			nav.cancel();
	});
	function unload(event: BeforeUnloadEvent): void {
		if (dirty || busy) {
			event.preventDefault();
			event.returnValue = '';
		}
	}
	async function command(path: string, method: 'POST' | 'PUT', body: unknown): Promise<void> {
		if (busy) return;
		busy = true;
		refreshVersion++;
		message = notice = '';
		try {
			await timetableCommand(`kholloscope/${year}/${path}`, method, body);
			await refresh();
		} catch (error) {
			message = error instanceof Error ? error.message : 'Action impossible.';
		} finally {
			busy = false;
		}
	}
	async function launch(): Promise<void> {
		await command('generation', 'POST', {
			expected_revision: view.source_revision,
			rules: { ...rules, optimize: true, preserve_locks: true }
		});
	}
	async function saveGeneration(): Promise<void> {
		if (!view.run || rulesChanged) return;
		await command('generation/save', 'POST', { expected_revision: view.run.revision });
		if (!message) await goto(resolve(`/timetable/kholloscope?school_year=${year}&tab=groups`));
	}
	function edit(session: GeneratedSession): void {
		editing = session;
		editDay = session.day;
		editTime = clock(session.start);
		editRoom = session.room_id;
		locked = session.locked ?? true;
	}
	async function saveMove(): Promise<void> {
		if (!editing || !view.run) return;
		const pieces = editTime.split(':').map(Number);
		const start = pieces[0] * 3600 + pieces[1] * 60 + (pieces[2] ?? 0);
		await command('generation/session', 'PUT', {
			expected_revision: view.run.revision,
			session_id: editing.id,
			day: editDay,
			start,
			room_id: editRoom,
			locked
		});
		if (!message) {
			editing = null;
			notice = 'Enregistrement effectué. L’affectation des groupes doit être revue.';
		}
	}
	async function saveGroups(): Promise<void> {
		if (!view.run || busy || (!!result?.mappings.length && !dirty)) return;
		assigning = busy = true;
		groupsVersion++;
		const version = ++refreshVersion;
		message = notice = '';
		try {
			await timetableCommand(`kholloscope/${year}/groups`, 'PUT', {
				expected_revision: view.run.revision,
				mode: rotation
			});
			const [nextView, nextGroups] = await Promise.all([
				read<GenerationView>('generation'),
				read<GenerationGroups>('groups')
			]);
			if (version !== refreshVersion) return;
			groups = nextGroups;
			view = nextView;
			rotation = nextGroups.mode ?? rotation;
			onupdate(view);
			notice = 'Groupes affectés au brouillon. Vérifiez le calendrier avant de publier.';
		} catch (error) {
			message = error instanceof Error ? error.message : 'Affectation impossible.';
		} finally {
			assigning = busy = false;
		}
	}
	function beginRemoval(): void {
		removalVersion = { revision: view.run?.revision ?? '', source: view.source_revision };
		removalText = '';
		removal = 1;
	}
	async function remove(): Promise<void> {
		await command('generation/remove', 'POST', {
			expected_revision: removalVersion.revision,
			expected_source_revision: removalVersion.source,
			scope: 'future',
			confirmation: removalText
		});
		if (!message) {
			removal = 0;
			notice = 'Kholloscope retiré des agendas.';
		}
	}
	async function apply(): Promise<void> {
		if (!view.run) return;
		await command('generation/apply', 'POST', {
			expected_revision: view.run.revision,
			confirmed_live: true
		});
		if (!message) confirmApply = false;
	}
</script>

<svelte:window onbeforeunload={unload} />
<section
	class="generation-panel"
	aria-label={mode === 'generation' ? 'Génération du calendrier' : 'Affectation des groupes'}
>
	{#if mode === 'generation'}
		<form
			class="workspace-panel mb-5"
			onsubmit={(event) => {
				event.preventDefault();
				void launch();
			}}
		>
			<fieldset disabled={busy || active || !canWrite || !!result?.applied}>
				<legend class="title is-4">Règles de génération</legend>
				<fieldset class="rule-section">
					<legend class="title is-6">Temps de calcul</legend>
					<label class="label"
						>Temps maximal de calcul (minutes)<input
							class="input"
							type="number"
							min="1"
							max="720"
							step="1"
							required
							value={rules.time_limit / 60}
							oninput={(event) => (rules.time_limit = event.currentTarget.valueAsNumber * 60)}
						/></label
					>
					<div class="rules-grid mt-4">
						{#each generationTimeStages as stage (stage.key)}
							<label class="label"
								>{stage.label} (%)<input
									class="input"
									type="number"
									min="1"
									max="97"
									step="1"
									required
									bind:value={rules[stage.key]}
								/></label
							>
						{/each}
					</div>
					{#if generationTimeTotal(rules) !== 100}<p class="help is-danger" role="alert">
							La répartition doit totaliser 100 % (actuellement {generationTimeTotal(rules)} %).
						</p>{/if}
				</fieldset>
				<fieldset class="rule-section">
					<legend class="title is-6">Volumes et rattrapages</legend>
					<div class="rules-grid">
						<label class="label"
							>Volumes fractionnaires<select class="input" bind:value={rules.rounding}
								><option value="none">Ne pas arrondir — suivre le cycle A/B</option><option
									value="floor">Arrondir à la séance inférieure</option
								><option value="ceil">Arrondir à la séance supérieure</option></select
							></label
						>
						<label class="label"
							>Rattrapages<select class="input" bind:value={rules.recovery_weeks}
								><option value={0}>Même semaine uniquement</option><option value={1}
									>Même semaine, sinon précédente ou suivante</option
								></select
							></label
						>
					</div>
				</fieldset>
				<fieldset class="rule-section">
					<legend class="title is-6">Journée et pause déjeuner</legend>
					<div class="rules-grid">
						<label class="label"
							>Khôlles maximales par groupe et par jour<input
								class="input"
								type="number"
								min="1"
								max="4"
								required
								bind:value={rules.max_per_day}
							/></label
						>
						{#if rules.teacher_lunch}<label class="label"
								>Pause continue entre 12 h et 14 h (minutes)<input
									class="input"
									type="number"
									min="20"
									max="120"
									required
									bind:value={rules.teacher_lunch_minutes}
								/></label
							>{/if}
					</div>
					<label class="checkbox mt-4"
						><input type="checkbox" bind:checked={rules.teacher_lunch} /> Conserver une pause déjeuner
						pour les intervenants</label
					>
				</fieldset>
				<div class="step-actions">
					<button
						class="button is-primary"
						disabled={!view.ready || generationTimeTotal(rules) !== 100}
						>Générer une proposition</button
					>
				</div>
			</fieldset>
		</form>
		{#if active}<button
				class="button is-light mb-4"
				disabled={busy}
				onclick={() => command('generation/cancel', 'POST', { run_id: view.run?.id })}
				>Annuler le calcul</button
			>{/if}
		{#if view.run}<div class="workspace-panel mb-5">
				<p role="status" class="label">
					{view.run.status === 'completed' &&
					!result?.saved &&
					!result?.mappings.length &&
					!result?.applied &&
					!result?.withdrawn
						? 'Solution trouvée — proposition à sauvegarder'
						: (statuses[view.run.status] ?? view.run.status)}
				</p>
				<p class="help">
					Journal actualisé chaque seconde pendant le calcul. Vous pouvez quitter cette page et
					retrouver le suivi.
				</p>
				<pre
					bind:this={logElement}
					class="solver-log"
					role="log"
					aria-label="Journal du calcul"
					aria-live="polite">{logText}</pre>
			</div>{/if}
	{:else if groups}
		<label class="label"
			>Rotation des groupes<select class="input" bind:value={rotation} disabled={!canEdit || busy}>
				<option value="fixed">Groupes fixes</option>
				<option value="weekly">Décalage +1 par semaine de khôlle</option>
				<option value="cycle">Décalage +1 par cycle de référence</option>
			</select></label
		>
		<p class="help mb-4">
			{rotation === 'fixed'
				? 'Chaque groupe conserve ses créneaux de référence.'
				: `Les groupes descendent d’un créneau par ${rotation === 'weekly' ? 'semaine de khôlle' : `cycle de ${result?.cycle_length ?? 2} semaines`}. La diversité des couples khôlleur/salle est privilégiée si le décalage doit être adapté.`}
			Les semaines de passage restent fixes ; les vacances ne font pas avancer la rotation.
		</p>
		{#if groups.rotation_adjustments}<p class="help mb-4">
				{groups.rotation_adjustments} affectations ajustées par rapport au décalage idéal pour la diversité
				et les contraintes.
			</p>{/if}
	{/if}
	{#if view.run?.stale && !result?.applied}<p class="notification is-warning is-light" role="alert">
			Les données ont changé depuis ce calcul. Régénérez avant de modifier, affecter ou appliquer ce
			brouillon.
		</p>{/if}

	{#if result}
		{#if mode === 'generation'}
			<div class="workspace-panel mb-4">
				<p>
					<strong>{result.sessions.length}</strong> séances annuelles ·
					<strong>{result.moved}</strong> déplacements lors de la génération.
				</p>
				{#each result.quotas.filter((q) => q.rounded) as quota (`${quota.calendar_id}-${quota.subject_id}`)}<p
						class="help"
					>
						{name(quota.calendar_id)} : volume arrondi de {quota.original_minutes / 60} h à {quota.sessions}
						séances par groupe.
					</p>{/each}
				{#if result.quotas.some((q) => q.cycle_based && q.min_sessions !== q.max_sessions)}<p
						class="help mt-2"
					>
						Le dernier cycle est incomplet : les groupes conservent le nombre de séances prévu par
						leur alternance (par exemple 12 ou 13). Ce n’est pas un arrondi.
					</p>{/if}
			</div>
		{/if}
		<KholloscopeCalendar
			{view}
			{catalog}
			sessions={mode === 'groups' && groups?.assigned_sessions?.length
				? groups.assigned_sessions
				: result.sessions}
			onedit={mode === 'generation' && canEdit && !busy ? edit : undefined}
			showChanges={mode === 'generation'}
		/>
		{#if mode === 'groups'}
			<section
				class="assignment-review workspace-panel mt-5"
				aria-label="Tableaux des affectations"
			>
				<div class="panel-heading">
					<h3 class="title is-5 mb-0">Colloscope des groupes</h3>
					{#if assigned.length && !dirty && !view.run?.stale}<a
							class="button is-link is-light"
							href={resolve(`/timetable/kholloscope/pdf?school_year=${year}`)}
							>Télécharger le kholloscope PDF</a
						>{/if}
				</div>
				{#if !assigned.length}<p>
						Affectez les groupes au brouillon pour consulter le colloscope.
					</p>{:else}
					<p class="help mb-4">
						Enregistré : <strong>{rotationLabels[savedRotation]}</strong>. Cliquez sur un groupe
						pour consulter sa séance.
					</p>
					{#if dirty}<p class="notification is-warning is-light">
							La rotation sélectionnée n’est pas encore enregistrée. Les tableaux montrent la
							dernière affectation validée.
						</p>{/if}
					{#each assignmentTables as calendar (calendar.id)}
						<details class="assignment-section">
							<summary>{calendar.name}</summary>
							{#each calendar.subjects as subject (subject.id)}
								<details class="assignment-subject">
									<summary>{subject.name}</summary>
									<div class="group-legend" aria-label="Légende des groupes">
										{#each calendar.groups as group (group)}<span
												class="group-chip"
												style:--group-hue={(group * 47) % 360}
												>G{String(group).padStart(2, '0')}</span
											>{/each}
									</div>
									<div
										class="colloscope-scroll"
										role="region"
										aria-label={'Colloscope ' + calendar.name + ' · ' + subject.name}
									>
										<table class="table is-bordered colloscope-table">
											<caption
												>{subject.name} · semaines du lundi indiqué · G = groupe · * = séance déplacée</caption
											>
											<thead
												><tr
													><th scope="col">Créneau / intervenant</th
													>{#each subject.weeks as week (week)}<th scope="col"
															>{week.slice(8, 10)}/{week.slice(5, 7)}<small
																>{week.slice(0, 4)}</small
															></th
														>{/each}</tr
												></thead
											>
											<tbody
												>{#each subject.rows as row (row.key)}<tr>
														<th scope="row"
															>{weekdays[row.weekday]} · {timetableClock(row.start)}<small
																>{catalog.teachers.find((t) => t.id === row.teacher)?.name}</small
															><small>{catalog.rooms.find((r) => r.id === row.room)?.name}</small
															></th
														>
														{#each subject.weeks as week (week)}<td
																>{#each row.cells.get(week) ?? [] as session (session.id)}<button
																		type="button"
																		class="group-chip"
																		style:--group-hue={((session.group ?? 0) * 47) % 360}
																		aria-label={'Groupe ' +
																			session.group +
																			', ' +
																			session.day +
																			' à ' +
																			timetableClock(session.start)}
																		onclick={() => (selectedAssignment = session)}
																		>G{String(session.group).padStart(2, '0')}{session.day !==
																			session.original_day ||
																		session.start !== session.original_start
																			? '*'
																			: ''}</button
																	>{:else}<span class="empty-cell" aria-label="Aucune khôlle"
																		>—</span
																	>{/each}</td
															>{/each}
													</tr>{/each}</tbody
											>
										</table>
									</div>
								</details>
							{/each}
						</details>
					{/each}
				{/if}
			</section>
		{:else}
			<div class="step-actions mt-5">
				<p class="help">
					{rulesChanged
						? 'Les règles ont changé. Régénérez la proposition avant de continuer.'
						: 'Enregistrez la proposition pour valider cette étape et ouvrir l’affectation des groupes.'}
				</p>
				<button
					class="button is-primary"
					disabled={!canEdit || busy || active || rulesChanged}
					onclick={saveGeneration}>Enregistrer et continuer</button
				>
			</div>
		{/if}
		{#if mode === 'groups'}<div class="buttons mt-5">
				<button
					class="button is-primary"
					class:is-loading={assigning}
					aria-busy={assigning}
					disabled={!canEdit || busy || (!!result.mappings.length && !dirty)}
					onclick={saveGroups}
					>{assigning ? 'Affectation en cours…' : 'Affecter les groupes'}</button
				>
				<button
					class="button is-danger"
					disabled={!canEdit || dirty || !result.mappings.length || busy}
					onclick={() => (confirmApply = true)}>Publier dans les agendas</button
				>
				{#if result.applied}<button
						class="button is-danger is-light"
						disabled={busy || !canWrite}
						onclick={beginRemoval}>Retirer le kholloscope des agendas</button
					>{/if}
			</div>{/if}
		{#if result.withdrawn}<p class="notification is-info is-light">
				Kholloscope retiré : {result.withdrawn.scope === 'all'
					? 'toutes les khôlles'
					: 'séances après la date du retrait'}. Les séances conservées restent dans les agendas.
				Régénérez une proposition avant une nouvelle affectation.
			</p>{/if}
	{/if}
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>
		<button
			class="button is-small"
			onclick={() =>
				refresh().catch((error) => {
					message = String(error);
				})}>Actualiser</button
		>{/if}
	{#if notice}<p class="notification is-success is-light" role="status">{notice}</p>{/if}
</section>
{#if selectedAssignment}
	{@const assignment = selectedAssignment}
	<Modal
		title={'Khôlle du groupe ' + selectedAssignment.group}
		busy={false}
		onclose={() => (selectedAssignment = null)}
	>
		<p class="mb-3">
			<strong>{catalog.subjects.find((s) => s.id === assignment.subject_id)?.name}</strong>
			· {name(selectedAssignment.calendar_id)}
		</p>
		<p>
			{selectedAssignment.day} · {timetableClock(selectedAssignment.start)} – {timetableClock(
				selectedAssignment.end
			)}
		</p>
		<p>
			{catalog.teachers.find((t) => t.id === assignment.teacher_id)?.name} · {catalog.rooms.find(
				(r) => r.id === assignment.room_id
			)?.name}
		</p>
		{#if selectedAssignment.original_day && (selectedAssignment.day !== selectedAssignment.original_day || selectedAssignment.start !== selectedAssignment.original_start)}<p
				class="help mt-3"
			>
				Initialement prévue le {selectedAssignment.original_day} à {timetableClock(
					selectedAssignment.original_start ?? selectedAssignment.start
				)}.
			</p>{/if}
	</Modal>{/if}
{#if editing}<Modal title="Modifier la séance" {busy} onclose={() => (editing = null)}>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void saveMove();
			}}
		>
			<p class="help mb-3">
				L’intervenant et la matière restent fixes pour conserver le service exact. Le serveur
				vérifie tous les chevauchements et repas avant de sauvegarder.
			</p>
			<label class="label"
				>Date<input class="input" type="date" required bind:value={editDay} /></label
			><label class="label"
				>Début<input class="input" type="time" step="1" required bind:value={editTime} /></label
			>
			<label class="label"
				>Salle<select class="input" bind:value={editRoom}
					>{#each catalog.rooms as room (room.id)}<option value={room.id}>{room.name}</option
						>{/each}</select
				></label
			>
			<label class="checkbox my-4"
				><input type="checkbox" bind:checked={locked} /> Verrouiller cette séance lors d’une nouvelle
				génération</label
			>
			{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}<button
				class="button is-primary"
				disabled={busy}>Enregistrer</button
			>
		</form></Modal
	>{/if}
{#if confirmApply}<Modal
		title="Appliquer le kholloscope"
		{busy}
		onclose={() => (confirmApply = false)}
		><p>
			Les séances seront ajoutées aux agendas avec les groupes choisis. Les calendriers déjà
			diffusés seront immédiatement mis à jour. Aucun cours existant ne sera supprimé.
		</p>
		{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
		<div class="buttons mt-4">
			<button class="button is-light" disabled={busy} onclick={() => (confirmApply = false)}
				>Annuler</button
			><button class="button is-primary" disabled={busy} onclick={apply}>Confirmer</button>
		</div></Modal
	>{/if}

{#if removal}<Modal
		title={removal === 1 ? 'Retirer le kholloscope' : 'Confirmer la suppression des khôlles'}
		{busy}
		onclose={() => (removal = 0)}
	>
		{#if removal === 1}<p>
				Le retrait concerne toutes les khôlles des agendas de cette proposition pour l’année
				sélectionnée, y compris les séances ajoutées ou modifiées manuellement. Les cours sont
				conservés.
			</p>
			<p class="mt-3">
				Par défaut, seules les séances strictement après aujourd’hui ({catalog.today}) seront
				supprimées. Les séances passées et celles d’aujourd’hui seront conservées.
			</p>
			<div class="buttons mt-4">
				<button class="button" onclick={() => (removal = 0)}>Annuler</button><button
					class="button is-danger"
					onclick={() => (removal = 2)}>Continuer</button
				>
			</div>
		{:else}<p>
				Toutes les khôlles après aujourd’hui seront supprimées de ces agendas. Cette suppression ne
				peut pas être annulée.
			</p>
			<label class="label mt-4"
				>Saisissez SUPPRIMER<input
					class="input"
					bind:value={removalText}
					autocomplete="off"
				/></label
			>
			{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
			<div class="buttons mt-4">
				<button class="button" disabled={busy} onclick={() => (removal = 1)}>Retour</button><button
					class="button is-danger"
					disabled={busy || removalText !== 'SUPPRIMER'}
					onclick={remove}>Supprimer les khôlles</button
				>
			</div>{/if}
	</Modal>{/if}

<style>
	.panel-heading {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		margin-bottom: 1.25rem;
	}
	.rule-section {
		padding: 0.65rem 0;
		border: 0;
		margin-top: 0.4rem;
	}
	.rule-section legend {
		padding-top: 0;
		margin-bottom: 0.5rem;
	}
	.rule-section .label {
		margin-bottom: 0;
		font-size: 0.85rem;
		font-weight: 500;
	}
	.rule-section > .label {
		max-width: 20rem;
	}
	.label {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.assignment-section,
	.assignment-subject {
		border: 1px solid var(--color-muted);
		border-radius: 0.5rem;
		margin-top: 0.75rem;
		padding: 0.75rem;
	}
	summary {
		cursor: pointer;
		font-weight: 600;
		padding: 0.25rem;
	}
	.assignment-review {
		min-width: 0;
	}
	.colloscope-scroll {
		overflow: auto;
		max-height: 36rem;
		margin-top: 1rem;
		border-radius: 0.4rem;
	}
	.colloscope-table {
		font-size: 0.8rem;
		border-collapse: separate;
		border-spacing: 0;
	}
	.colloscope-table th,
	.colloscope-table td {
		text-align: center;
		vertical-align: middle;
		min-width: 4rem;
		padding: 0.5rem 0.35rem;
	}
	.colloscope-table th:first-child {
		position: sticky;
		left: 0;
		min-width: 12rem;
		text-align: left;
		background: var(--color-paper);
		color: var(--color-ink);
		z-index: 1;
	}
	.colloscope-table thead th {
		position: sticky;
		top: 0;
		background: var(--color-paper);
		color: var(--color-ink);
		z-index: 2;
	}
	.colloscope-table thead th:first-child {
		z-index: 3;
	}
	.colloscope-table small {
		display: block;
		font-weight: normal;
		color: var(--color-muted);
	}
	.group-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 1rem;
	}
	.group-chip {
		display: inline-block;
		border: 1px solid hsl(var(--group-hue) 40% 65%);
		border-radius: 0.3rem;
		padding: 0.35rem 0.4rem;
		margin: 0.1rem;
		background: hsl(var(--group-hue) 65% 92%);
		color: hsl(var(--group-hue) 55% 20%);
		font: inherit;
		font-weight: 700;
		white-space: nowrap;
	}
	button.group-chip {
		cursor: pointer;
	}
	button.group-chip:hover {
		outline: 2px solid currentColor;
	}
	.empty-cell {
		color: var(--color-muted);
	}
	.generation-panel {
		margin-top: 1rem;
	}
	.rules-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
		gap: 0.65rem 1rem;
	}
	.solver-log {
		max-height: 20rem;
		overflow: auto;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		background: var(--color-paper);
		color: var(--color-ink);
		font-size: 0.75rem;
	}
	.checkbox {
		display: block;
	}
</style>
