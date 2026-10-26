<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { beforeNavigate, goto, invalidateAll } from '$app/navigation';
	import { activeSubjects, command, read, statusLabels } from '#lib/dashboard';
	import type { CourseImpact, Subject } from '#lib/site';
	import { canJoinPromotion, roleSelectionError, sameRoles } from '#lib/roles';
	import RoleSelector from '../RoleSelector.svelte';
	import RoleBadges from '../RoleBadges.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import GroupTags from '../GroupTags.svelte';
	import type { FullProfile, SchoolProfile } from '#lib/types';
	import Icon from '../Icon.svelte';
	import Modal from '../Modal.svelte';
	import CommunePicker from '../CommunePicker.svelte';
	import TagSelector from '../TagSelector.svelte';
	let { profile, currentUserId }: { profile: FullProfile; currentUserId: number } = $props();
	function draftFor(value: FullProfile) {
		return {
			first_name: value.first_name,
			last_name: value.last_name,
			email: value.email,
			roles: [...value.roles],
			subject_ids: [...(value.subject_ids ?? [])],
			birth_date: value.profile.birth_date ?? '',
			city: value.profile.city,
			postal_code: value.profile.postal_code,
			commune_code: value.profile.commune_code,
			previous_school: value.profile.previous_school ?? '',
			phone: value.profile.phone ?? '',
			orientation_project: value.profile.orientation_project ?? '',
			bac: {
				label: value.profile.baccalaureate?.label ?? '',
				year: value.profile.baccalaureate?.year ?? undefined,
				overall_grade: value.profile.baccalaureate?.overall_grade ?? undefined,
				subjects:
					value.profile.baccalaureate?.subjects.map((subject) => ({
						name: subject.name,
						grade: subject.grade ?? undefined
					})) ?? ([] as { name: string; grade: number | undefined }[])
			},
			adult: {
				first_name: value.profile.reference_adult?.first_name ?? '',
				last_name: value.profile.reference_adult?.last_name ?? '',
				phone: value.profile.reference_adult?.phone ?? ''
			}
		};
	}
	let current = $state(untrack(() => profile));
	let draft = $state(untrack(() => draftFor(profile)));
	let original = $state(untrack(() => JSON.stringify(draftFor(profile))));
	const dirty = $derived(JSON.stringify(draft) !== original);
	let busy = $state(false);
	let message = $state('');
	let success = $state(false);
	let saveFeedback = $state<HTMLParagraphElement>();
	let leave = $state<(() => void) | null>(null);
	let confirmRoles = $state(false);
	let subjects = $state<Subject[]>([]);
	let subjectsLoading = $state(false);
	let impacts = $state<CourseImpact[]>([]);
	onMount(async () => {
		if (!profile.can_edit_all) return;
		subjectsLoading = true;
		try {
			subjects = await activeSubjects();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			subjectsLoading = false;
		}
	});
	const rolesChanged = $derived(!sameRoles(draft.roles, current.roles));
	let allowNavigation = false;
	beforeNavigate((navigation) => {
		if (allowNavigation || !dirty) return;
		if (navigation.willUnload) {
			navigation.cancel();
			return;
		}
		navigation.cancel();
		const target = navigation.to?.url;
		if (!target) return;
		leave = () => {
			allowNavigation = true;
			if (navigation.type === 'popstate' && navigation.delta) window.history.go(navigation.delta);
			else {
				// SvelteKit's navigation target already contains the resolved application base path.
				// eslint-disable-next-line svelte/no-navigation-without-resolve
				void goto(target);
			}
		};
	});
	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (busy) return;
		if (current.can_edit_all) {
			message = roleSelectionError(draft.roles);
			if (message) return;
			const nextRoles = draft.roles;
			const removed = current.subject_ids.filter((id) => !draft.subject_ids.includes(id));

			if (rolesChanged || removed.length) {
				busy = true;
				message = '';
				try {
					const courses = await read<CourseImpact[]>('courseImpact', { id: current.id });
					impacts = courses.filter((course) => {
						const hadTeaching =
							current.roles.includes('teacher') && current.subject_ids.includes(course.subject_id);
						const hasTeaching =
							nextRoles.includes('teacher') && draft.subject_ids.includes(course.subject_id);
						return (
							(hadTeaching && !hasTeaching) ||
							(current.roles.includes('kholleur') &&
								!nextRoles.includes('kholleur') &&
								!hasTeaching &&
								!nextRoles.includes('admin'))
						);
					});
					confirmRoles = true;
				} catch (cause) {
					message = (cause as Error).message;
				} finally {
					busy = false;
				}
				return;
			}
		}
		await persist();
	}
	async function persist(acknowledged = false): Promise<void> {
		if (busy) return;
		confirmRoles = false;
		busy = true;
		message = '';
		success = false;
		try {
			let changes: Record<string, unknown>;
			if (current.can_edit_all) {
				const bac = draft.bac;
				const school: SchoolProfile = {
					birth_date: draft.birth_date || null,
					city: draft.city,
					postal_code: draft.postal_code,
					commune_code: draft.commune_code,
					previous_school: draft.previous_school.trim() || null,
					phone: draft.phone.trim() || null,
					orientation_project: draft.orientation_project.trim() || null,
					baccalaureate:
						bac.label ||
						bac.year !== undefined ||
						bac.overall_grade !== undefined ||
						bac.subjects.length
							? {
									label: bac.label.trim() || null,
									year: bac.year ?? null,
									overall_grade: bac.overall_grade ?? null,
									subjects: bac.subjects.map((subject) => ({
										name: subject.name.trim(),
										grade: subject.grade ?? null
									}))
								}
							: null,
					reference_adult:
						draft.adult.first_name || draft.adult.last_name || draft.adult.phone
							? { ...draft.adult }
							: null
				};
				changes = {};
				const nextSubjects = draft.roles.some((role) => ['teacher', 'kholleur'].includes(role))
					? draft.subject_ids
					: [];
				if ([...nextSubjects].sort().join(',') !== [...current.subject_ids].sort().join(','))
					changes.subject_ids = nextSubjects;
				if (acknowledged) changes.acknowledge_course_impact = true;
				if (rolesChanged) changes.roles = draft.roles;
				for (const key of ['first_name', 'last_name', 'email'] as const)
					if (draft[key] !== current[key]) changes[key] = draft[key];
				for (const key of Object.keys(school) as (keyof SchoolProfile)[])
					if (JSON.stringify(school[key]) !== JSON.stringify(current.profile[key]))
						changes[key] = school[key];
				if (['city', 'postal_code', 'commune_code'].some((key) => key in changes)) {
					changes.city = school.city;
					changes.postal_code = school.postal_code;
					changes.commune_code = school.commune_code;
				}
			} else changes = { orientation_project: draft.orientation_project.trim() || null };
			current = await command<FullProfile>('updateProfile', {
				id: current.id,
				data: { expected_version: current.profile_version, ...changes }
			});
			draft = draftFor(current);
			original = JSON.stringify(draft);
			success = true;
			await invalidateAll();
			await tick();
			saveFeedback?.focus({ preventScroll: true });
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	const adultRequired = $derived(
		Boolean(draft.adult.first_name || draft.adult.last_name || draft.adult.phone)
	);
</script>

<header class="profile-page-hero">
	<div class="avatar large">{current.first_name.slice(0, 1)}{current.last_name.slice(0, 1)}</div>
	<div>
		<p class="eyebrow">Fiche du compte</p>
		<h1 class="title is-2 mb-2">{current.first_name} {current.last_name}</h1>
		<p class="muted">
			@{current.username} · <RoleBadges roles={current.roles} />
			{#if current.age !== null}
				· {current.age} ans{/if}
		</p>
	</div>
	<span class="account-status" class:archived={current.status === 'disabled'}
		>{statusLabels[current.status]}</span
	>
</header>
<p class="help mb-5">
	{current.can_edit_all
		? 'Vous pouvez modifier les informations de cette fiche. L’identifiant reste inchangé.'
		: 'Vous pouvez modifier uniquement le projet d’orientation des élèves de vos promotions.'}
</p>
<form onsubmit={save} aria-busy={busy}>
	{#if current.can_edit_all}
		<section class="workspace-panel mb-5">
			<h2 class="title is-5"><Icon name="admin" />Rôles et accès</h2>
			<div class="field">
				<RoleSelector
					bind:selected={draft.roles}
					disabled={busy}
					preserveAdmin={current.id === currentUserId}
				/>
			</div>
			{#if rolesChanged}
				<p class="notification is-warning is-light" role="status">
					Les accès de ce compte changeront après confirmation de l’enregistrement.
				</p>
			{/if}
			{#if draft.roles.some((role) => ['teacher', 'kholleur'].includes(role))}
				<div class="field">
					{#if subjectsLoading}<p role="status">Chargement des matières…</p>{:else}<TagSelector
							legend="Matières affectées"
							options={subjects.map((subject) => ({
								value: subject.id,
								label: subject.name,
								color: subject.color,
								icon: subject.icon
							}))}
							bind:selected={draft.subject_ids}
							disabled={busy || current.status === 'disabled'}
						/>{/if}
					<p class="help">
						Sans matière, un enseignant ne peut pas créer de cours. Un khôlleur doit être ajouté
						explicitement comme collaborateur pour consulter un cours : ses matières ne lui donnent
						aucun accès automatique.
					</p>
				</div>
			{/if}
		</section>
	{/if}
	<section class="workspace-panel mb-5" aria-label="Promotions et groupes">
		<h2 class="title is-5"><Icon name="promotions" />Promotions et groupes</h2>
		{#if !current.can_edit_all}<p class="muted text-small mb-3">
				Promotions partagées avec vous.
			</p>{/if}
		{#each current.promotions as promotion (promotion.id)}
			<div class="membership-row">
				<PromotionTag {promotion} />
				<GroupTags assignments={current.group_assignments} promotionId={promotion.id} />
			</div>
		{:else}<p class="muted">Aucune promotion affectée.</p>{/each}
	</section>
	<div class="school-profile-grid">
		<section class="workspace-panel profile-information accent-blue">
			<h2 class="title is-5"><Icon name="profile" />Identité et coordonnées</h2>
			<fieldset disabled={busy || !current.can_edit_all}>
				<div class="form-grid">
					<div class="field">
						<label class="label" for="profile-first">Prénom</label><input
							id="profile-first"
							class="input"
							bind:value={draft.first_name}
							required
							maxlength="100"
							autocomplete="given-name"
						/>
					</div>
					<div class="field">
						<label class="label" for="profile-last">Nom</label><input
							id="profile-last"
							class="input"
							bind:value={draft.last_name}
							required
							maxlength="100"
							autocomplete="family-name"
						/>
					</div>
				</div>
				<div class="field">
					<label class="label" for="profile-email">Email</label><input
						id="profile-email"
						class="input"
						type="email"
						bind:value={draft.email}
						required
						maxlength="254"
						autocomplete="email"
					/>
				</div>
				<div class="form-grid">
					<div class="field">
						<label class="label" for="profile-birth">Date de naissance</label><input
							id="profile-birth"
							class="input"
							type="date"
							bind:value={draft.birth_date}
							max={new Date().toISOString().slice(0, 10)}
						/>
					</div>
					<div class="field">
						<label class="label" for="profile-phone">Téléphone</label><input
							id="profile-phone"
							class="input"
							type="tel"
							bind:value={draft.phone}
							maxlength="40"
							autocomplete="tel"
							placeholder="06… ou +33…"
						/>
					</div>
				</div>
				<CommunePicker
					bind:city={draft.city}
					bind:postalCode={draft.postal_code}
					bind:communeCode={draft.commune_code}
					disabled={busy || !current.can_edit_all}
				/>
			</fieldset>
		</section>
		<section class="workspace-panel profile-information accent-violet">
			<h2 class="title is-5"><Icon name="school" />Parcours scolaire</h2>
			<fieldset disabled={busy || !current.can_edit_all}>
				<div class="field">
					<label class="label" for="profile-school">Établissement précédent</label><input
						id="profile-school"
						class="input"
						bind:value={draft.previous_school}
						maxlength="200"
					/>
				</div>
				<div class="field">
					<label class="label" for="profile-bac">Intitulé du baccalauréat</label><input
						id="profile-bac"
						class="input"
						bind:value={draft.bac.label}
						maxlength="100"
						placeholder="Général, STI2D…"
					/>
				</div>
				<div class="form-grid">
					<div class="field">
						<label class="label" for="profile-year">Année d’obtention</label><input
							id="profile-year"
							class="input"
							type="number"
							min="1900"
							max={new Date().getFullYear()}
							step="1"
							bind:value={draft.bac.year}
						/>
					</div>
					<div class="field">
						<label class="label" for="profile-grade">Moyenne générale /20</label><input
							id="profile-grade"
							class="input"
							type="number"
							min="0"
							max="20"
							step="any"
							bind:value={draft.bac.overall_grade}
						/>
					</div>
				</div>
				<h3 class="label mt-4">Spécialités et options principales</h3>
				{#each draft.bac.subjects as subject, index (index)}<div class="subject-editor">
						<div>
							<label class="label" for={`subject-name-${index}`}>Option {index + 1}</label><input
								id={`subject-name-${index}`}
								class="input"
								bind:value={subject.name}
								required
								maxlength="100"
								placeholder="Mathématiques, SI…"
							/>
						</div>
						<div>
							<label class="label" for={`subject-grade-${index}`}>Note /20</label><input
								id={`subject-grade-${index}`}
								class="input"
								type="number"
								min="0"
								max="20"
								step="any"
								bind:value={subject.grade}
							/>
						</div>
						{#if current.can_edit_all}<button
								type="button"
								class="icon-button"
								aria-label={`Retirer l’option ${index + 1}`}
								onclick={() => draft.bac.subjects.splice(index, 1)}><Icon name="close" /></button
							>{/if}
					</div>{/each}
				{#if current.can_edit_all}<button
						type="button"
						class="button is-light is-small mt-3"
						disabled={draft.bac.subjects.length >= 20}
						onclick={() => draft.bac.subjects.push({ name: '', grade: undefined })}
						><Icon name="plus" />Ajouter une option</button
					>{/if}
			</fieldset>
		</section>
		<section class="workspace-panel profile-information accent-green">
			<h2 class="title is-5"><Icon name="orientation" />Projet d’orientation</h2>
			<label class="label" for="profile-orientation">Projet, filière ou concours envisagés</label>
			<textarea
				id="profile-orientation"
				class="textarea"
				bind:value={draft.orientation_project}
				maxlength="200"
				disabled={busy || !current.can_edit_orientation}
				rows="4"></textarea>
			<p class="help has-text-right">{draft.orientation_project.length} / 200 caractères</p>
		</section>
		<section class="workspace-panel profile-information accent-orange">
			<h2 class="title is-5"><Icon name="adult" />Adulte référent à contacter</h2>
			<fieldset disabled={busy || !current.can_edit_all}>
				<div class="form-grid">
					<div class="field">
						<label class="label" for="adult-first">Prénom du référent</label><input
							id="adult-first"
							class="input"
							bind:value={draft.adult.first_name}
							required={adultRequired}
							maxlength="100"
						/>
					</div>
					<div class="field">
						<label class="label" for="adult-last">Nom du référent</label><input
							id="adult-last"
							class="input"
							bind:value={draft.adult.last_name}
							required={adultRequired}
							maxlength="100"
						/>
					</div>
				</div>
				<div class="field">
					<label class="label" for="adult-phone">Téléphone du référent</label><input
						id="adult-phone"
						class="input"
						type="tel"
						bind:value={draft.adult.phone}
						required={adultRequired}
						maxlength="40"
					/>
				</div>
				<p class="help">
					Contact facultatif. Renseignez les trois champs pour ajouter un référent.
				</p>
			</fieldset>
		</section>
	</div>
	<footer class="profile-save-bar">
		<div>
			{#if message}<p class="has-text-danger" role="alert">{message}</p>{:else if dirty}<p
					class="muted"
				>
					Des modifications ne sont pas encore enregistrées.
				</p>{:else if success}<p
					class="has-text-success"
					role="status"
					tabindex="-1"
					bind:this={saveFeedback}
				>
					<Icon name="check" />Fiche enregistrée.
				</p>{:else}<p class="muted">Toutes les modifications sont enregistrées ensemble.</p>{/if}
		</div>
		<button
			class="button is-primary"
			type="submit"
			class:is-loading={busy}
			disabled={busy || !dirty || !current.can_edit_orientation}
			><Icon name="save" />Enregistrer la fiche</button
		>
	</footer>
</form>
{#if confirmRoles}
	<Modal title="Confirmer le changement des accès" onclose={() => (confirmRoles = false)}>
		<div class="notification is-warning is-light" role="alert">
			<p>
				<strong
					>Attention : vous allez modifier les accès de {current.first_name}
					{current.last_name}.</strong
				>
			</p>
			<p class="mt-3">Rôles actuels : <RoleBadges roles={current.roles} /></p>
			<p class="mt-3">Nouveaux rôles : <RoleBadges roles={draft.roles} /></p>
			{#if rolesChanged && !canJoinPromotion(draft.roles) && current.promotions.length}
				<p class="notification is-warning is-light mt-3">
					Ce compte perd son éligibilité aux promotions. {current.promotions.length} affectation{current
						.promotions.length === 1
						? ''
						: 's'} à une promotion {current.promotions.length === 1
						? 'sera retirée'
						: 'seront retirées'} automatiquement dès l’enregistrement, y compris pour les promotions archivées.
				</p>
			{/if}
			<p class="mt-3">
				Les droits associés seront appliqués dès l’enregistrement. Êtes-vous sûr de ce changement ?
			</p>
			{#if impacts.length}<p class="mt-3">
					<strong
						>Ce compte est associé à {impacts.length} cours concerné{impacts.length === 1
							? ''
							: 's'}. Il perdra les droits correspondants dès l’enregistrement.</strong
					>
				</p>
				<ul class="mt-3">
					{#each impacts as course (course.id)}<li>
							{course.title} · {course.responsible ? 'responsable principal' : 'collaborateur'}
						</li>{/each}
				</ul>
				<p class="mt-3">
					Un administrateur peut nommer un nouveau responsable depuis chaque cours. Les affectations
					retirées et les collaborations concernées devront être accordées à nouveau pour rétablir
					les droits.
				</p>{/if}
		</div>
		<div class="dialog-actions">
			<button type="button" class="button is-light" onclick={() => (confirmRoles = false)}
				>Annuler</button
			>
			<button type="button" class="button is-warning" onclick={() => persist(true)}
				>Confirmer et enregistrer</button
			>
		</div>
	</Modal>
{/if}
{#if leave}<Modal title="Modifications non enregistrées" onclose={() => (leave = null)}>
		<p role="alert">
			Vous avez modifié cette fiche. Quitter maintenant entraînera la perte des modifications.
		</p>
		<div class="dialog-actions">
			<button class="button is-light" onclick={() => (leave = null)}>Rester sur la fiche</button
			><button
				class="button is-danger"
				onclick={() => {
					const proceed = leave;
					leave = null;
					proceed?.();
				}}>Quitter sans enregistrer</button
			>
		</div>
	</Modal>{/if}
