<script lang="ts">
	import { onMount } from 'svelte';
	import {
		lessonCommand,
		LessonError,
		periodLabel,
		type LessonDetail,
		type LessonPerson
	} from '#lib/lessons';
	import type { Promotion } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import AccountIdentity from '../AccountIdentity.svelte';
	let {
		lesson,
		onsaved,
		onclose
	}: { lesson: LessonDetail; onsaved: (lesson: LessonDetail) => void; onclose: () => void } =
		$props();
	let options = $state<Promotion[]>([]);
	let loading = $state(true);
	let busy = $state(false);
	let message = $state('');
	let selectedPromotion = $state('');
	let customPeriod = $state(false);
	let start = $state('');
	let end = $state('');
	let query = $state('');
	let teachers = $state<LessonPerson[]>([]);
	let searching = $state(true);
	let searchMessage = $state('');
	let ready = $state(false);
	const candidates = $derived(
		teachers.filter(
			(person) =>
				person.id !== lesson.creator.id &&
				person.id !== lesson.responsible.id &&
				!lesson.collaborators.some((existing) => existing.id === person.id)
		)
	);
	async function read<T>(params: Record<string, string>, signal?: AbortSignal): Promise<T> {
		const response = await fetch(
			`/lessons/options?${new URLSearchParams({ lessonId: String(lesson.id), ...params })}`,
			{ cache: 'no-store', signal }
		);
		const value = await response.json();
		if (!response.ok)
			throw new LessonError(response.status, value.message || 'La demande a échoué.');
		return value as T;
	}
	onMount(() => {
		ready = true;
		const abort = new AbortController();
		void (async () => {
			try {
				for (let offset = 0; ; offset += 50) {
					const page = await read<Promotion[]>(
						{ resource: 'promotions', offset: String(offset) },
						abort.signal
					);
					options.push(...page);
					if (page.length < 50) break;
				}
			} catch (cause) {
				if (!abort.signal.aborted) message = (cause as Error).message;
			} finally {
				loading = false;
			}
		})();
		return () => {
			abort.abort();
		};
	});
	$effect(() => {
		const q = query.trim();
		const lessonId = lesson.id;
		void lesson.version;
		if (!ready || !lesson.can_manage_collaborators) return;
		const abort = new AbortController();
		teachers = [];
		searching = true;
		searchMessage = '';
		const timer = setTimeout(
			async () => {
				try {
					const results = await read<LessonPerson[]>(
						{ resource: 'teachers', lessonId: String(lessonId), q },
						abort.signal
					);
					if (!abort.signal.aborted) teachers = results;
				} catch (cause) {
					if (!abort.signal.aborted) searchMessage = (cause as Error).message;
				} finally {
					if (!abort.signal.aborted) searching = false;
				}
			},
			q ? 180 : 0
		);
		return () => {
			clearTimeout(timer);
			abort.abort();
		};
	});
	function choosePromotion(): void {
		const promotion = options.find((item) => String(item.id) === selectedPromotion);
		if (!promotion) return;
		const grant = lesson.promotions.find((item) => item.promotion_id === promotion.id);
		start = grant?.starts_on ?? `${String(promotion.year).padStart(4, '0')}-09-01`;
		end = grant?.ends_on ?? `${String(promotion.year + 1).padStart(4, '0')}-08-31`;
		customPeriod = !!grant;
	}
	async function mutate(command: string, payload: object): Promise<void> {
		busy = true;
		message = '';
		try {
			onsaved(await lessonCommand<LessonDetail>(command, { lessonId: lesson.id, ...payload }));
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function grant(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		await mutate('grantPromotion', {
			promotionId: Number(selectedPromotion),
			data: {
				expected_version: lesson.version,
				...(customPeriod ? { starts_on: start, ends_on: end } : {})
			}
		});
	}
</script>

<Modal
	title="Accès et collaborateurs"
	description="Gérez qui peut consulter et modifier ce cours."
	drawer
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<section class="settings-section">
		<h3 class="title is-5">Les promotions</h3>
		<p class="muted text-small mb-4">
			Les élèves voient tous les cours au catalogue. Seules les promotions autorisées peuvent ouvrir
			cette page.
		</p>
		{#each lesson.promotions as grant (grant.promotion_id)}<div class="access-row">
				<span class="promotion-dot" style:background={grant.color}></span>
				<div>
					<strong>{grant.identifier} · {grant.year}</strong>
					<p class="muted text-small">{periodLabel(grant.starts_on, grant.ends_on)}</p>
					{#if !grant.is_active}<p class="help is-warning">
							Promotion archivée : accès suspendu.
						</p>{:else if grant.ends_on < lesson.today}<p class="help is-warning">
							Accès expiré.
						</p>{/if}
				</div>
				<button
					class="icon-button"
					aria-label={`Révoquer l’accès de ${grant.identifier}`}
					title="Révoquer"
					disabled={busy}
					onclick={() => {
						if (
							window.confirm(`Révoquer l’accès de la promotion ${grant.identifier} ${grant.year} ?`)
						)
							void mutate('revokePromotion', {
								promotionId: grant.promotion_id,
								data: { expected_version: lesson.version }
							});
					}}><Icon name="remove" /></button
				>
			</div>{/each}
		{#if !lesson.promotions.length}<p class="notification is-warning is-light">
				Aucune promotion autorisée. Les élèves ne peuvent pas ouvrir ce cours.
			</p>{/if}
		{#if loading}<p role="status">Chargement des promotions…</p>{:else}<form
				onsubmit={grant}
				class="grant-form"
			>
				<div class="field">
					<label class="label" for="grant-promotion"
						>Ajouter ou renouveler une promotion active</label
					>
					<div class="select is-fullwidth">
						<select
							id="grant-promotion"
							bind:value={selectedPromotion}
							onchange={choosePromotion}
							required
							><option value="">Choisir une promotion</option
							>{#each options as promotion (promotion.id)}<option value={String(promotion.id)}
									>{promotion.identifier} · {promotion.year}</option
								>{/each}</select
						>
					</div>
				</div>
				{#if selectedPromotion}<label class="checkbox"
						><input type="checkbox" bind:checked={customPeriod} />Personnaliser les dates</label
					>{#if customPeriod}<div class="grant-dates">
							<div>
								<label class="label" for="grant-start">Début inclus</label><input
									id="grant-start"
									class="input"
									type="date"
									bind:value={start}
									required
								/>
							</div>
							<div>
								<label class="label" for="grant-end">Fin incluse</label><input
									id="grant-end"
									class="input"
									type="date"
									bind:value={end}
									min={start}
									required
								/>
							</div>
						</div>{:else}<p class="help mt-2">
							{periodLabel(start, end)} · fin d’année fixée au 31 août.
						</p>{/if}<button
						type="submit"
						class="button is-primary mt-3"
						class:is-loading={busy}
						disabled={busy || (customPeriod && end < start)}>Enregistrer l’accès</button
					>{/if}
			</form>{/if}
	</section>
	<section class="settings-section">
		<h3 class="title is-5">L’équipe enseignante</h3>
		<div class="access-row">
			<Icon name="teacher" />
			<div>
				<strong>{lesson.responsible.label}</strong>
				<p class="muted text-small">
					Responsable principal{!lesson.responsible.can_edit ? ' · rôle enseignant inactif' : ''}
				</p>
			</div>
		</div>
		{#each lesson.collaborators as person (person.id)}<div class="access-row">
				<Icon name="teacher" />
				<div>
					<strong>{person.label}</strong>
					<p class="muted text-small">
						{person.role === 'kholleur'
							? 'Khôlleur · lecture seule, contenus masqués inclus'
							: person.can_edit
								? 'Collaborateur'
								: 'Droits d’édition suspendus'}
					</p>
				</div>
				{#if lesson.can_manage_collaborators}<button
						class="icon-button"
						title="Retirer"
						aria-label={`Retirer ${person.label}`}
						disabled={busy}
						onclick={() => {
							if (window.confirm(`Retirer ${person.label} des collaborateurs ?`))
								void mutate('removeCollaborator', {
									userId: person.id,
									data: { expected_version: lesson.version }
								});
						}}><Icon name="remove" /></button
					>{/if}
			</div>{/each}
		{#if lesson.can_manage_collaborators}<div class="teacher-search">
				<label class="label" for="teacher-query">Ajouter un enseignant ou un khôlleur</label>
				<div class="search-field">
					<Icon name="search" size={16} />
					<input
						id="teacher-query"
						class="input"
						type="search"
						bind:value={query}
						maxlength="100"
						placeholder="Prénom ou nom"
						disabled={busy}
						aria-controls="collaborator-candidates"
					/>
				</div>
			</div>
			<div id="collaborator-candidates" class="candidate-list" aria-busy={searching}>
				{#if searching}<p class="help" role="status">Recherche…</p>
				{:else if searchMessage}<p class="help is-danger" role="alert">{searchMessage}</p>
				{:else}{#each candidates as person (person.id)}<div class="access-row candidate-row">
							<div>
								<AccountIdentity user={person} />
							</div>
							<button
								class="icon-button"
								type="button"
								title="Ajouter"
								aria-label={`Ajouter ${person.label}`}
								disabled={busy}
								onclick={() =>
									mutate('addCollaborator', {
										userId: person.id,
										data: { expected_version: lesson.version }
									})}><Icon name="plus" size={14} /></button
							>
						</div>{/each}{#if !candidates.length}<p class="muted text-small mt-3" role="status">
							Aucun enseignant éligible ou khôlleur actif trouvé.
						</p>{/if}{/if}
			</div>
			<p class="help mt-3">
				L’ajout est immédiat. Un enseignant possédant la matière peut éditer le cours et ses accès.
				Un khôlleur voit tous les contenus en lecture seule. Les collaborateurs ne peuvent pas
				inviter d’autres collaborateurs.
			</p>
		{:else}<p class="help mt-3">
				Seul le responsable ou un administrateur peut gérer les collaborateurs.
			</p>{/if}
	</section>
</Modal>

<style>
	.settings-section + .settings-section {
		margin-top: 2.5rem;
		padding-top: 2rem;
		border-top: var(--border-thin);
	}
	.access-row {
		display: flex;
		gap: 0.7rem;
		align-items: center;
		padding: 0.9rem 0;
		border-bottom: 1px solid var(--color-paper);
	}
	.access-row > div {
		flex: 1;
		min-width: 0;
	}
	.grant-form {
		margin-top: 1.4rem;
		padding: 1rem;
		background: var(--color-paper);
		border-radius: 0.7rem;
	}
	.grant-dates {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: 0.6rem;
		margin-top: 1rem;
	}
	.teacher-search {
		margin-top: 1.5rem;
	}
	.candidate-list {
		margin-top: 0.5rem;
	}
	.candidate-row {
		padding: 0.65rem;
		border: var(--border-thin);
		border-radius: var(--radius-small);
		background: var(--color-subtle);
		margin-bottom: 0.4rem;
	}
	.checkbox {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}
</style>
