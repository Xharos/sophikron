<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { activePromotions, command } from '#lib/dashboard';
	import { canJoinPromotion, roleSelectionError } from '#lib/roles';
	import RoleSelector from '../RoleSelector.svelte';
	import type { AccessInvitation, Promotion, User } from '#lib/types';
	import Modal from '../Modal.svelte';
	import Icon from '../Icon.svelte';
	import PromotionTag from '../PromotionTag.svelte';
	import InvitationResult from '../InvitationResult.svelte';
	let {
		onclose,
		oncreated,
		promotionId
	}: { onclose: () => void; oncreated: () => void; promotionId?: number } = $props();
	let first = $state('');
	let last = $state('');
	let email = $state('');
	let roles = $state<string[]>(['user']);
	const eligible = $derived(canJoinPromotion(roles));
	let promotions = $state<Promotion[]>([]);
	let selected = $state<number[]>(untrack(() => (promotionId ? [promotionId] : [])));
	let promotionError = $state('');
	let busy = $state(false);
	let message = $state('');
	let created = $state<User | null>(null);
	let invitation = $state<AccessInvitation | null>(null);
	onMount(async () => {
		try {
			promotions = await activePromotions();
		} catch (cause) {
			promotionError = (cause as Error).message;
		}
	});
	async function create(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		message = roleSelectionError(roles);
		if (message) return;
		busy = true;
		message = '';
		try {
			created = await command<User>('createUser', {
				data: {
					first_name: first,
					last_name: last,
					email,
					roles,
					promotion_ids: eligible ? selected : []
				}
			});
			oncreated();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function invite(): Promise<void> {
		if (!created) return;
		busy = true;
		message = '';
		try {
			invitation = await command<AccessInvitation>('invitation', { id: created.id });
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	function another(): void {
		created = null;
		invitation = null;
		first = '';
		last = '';
		email = '';
		roles = ['user'];
		message = '';
	}
</script>

<Modal
	title="Créer un compte"
	description="Un identifiant sera généré automatiquement."
	{busy}
	{onclose}
>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if created}
		<div class="success-panel">
			<Icon name="check" size={25} />
			<h3 class="title is-5 mt-3">Compte créé</h3>
			<p>{created.first_name} {created.last_name}</p>
			<p class="muted mt-2">Identifiant : <strong>{created.username}</strong></p>
		</div>
		{#if invitation}<InvitationResult {invitation} />{:else}<p class="muted mt-4 mb-3">
				Préparez une invitation pour permettre la connexion.
			</p>
			<button class="button is-primary" class:is-loading={busy} disabled={busy} onclick={invite}
				><Icon name="email" />Préparer l’invitation</button
			>{/if}
		<div class="dialog-actions">
			<button class="button is-light" disabled={busy} onclick={onclose}>Terminer</button>
			<button class="button is-primary" disabled={busy} onclick={another}
				><Icon name="plus" />Créer un autre compte</button
			>
		</div>
	{:else}
		<form onsubmit={create} aria-busy={busy}>
			<div class="form-grid">
				<div class="field">
					<label class="label" for="new-first">Prénom</label><input
						id="new-first"
						class="input"
						bind:value={first}
						autocomplete="given-name"
						maxlength="100"
						required
					/>
				</div>
				<div class="field">
					<label class="label" for="new-last">Nom</label><input
						id="new-last"
						class="input"
						bind:value={last}
						autocomplete="family-name"
						maxlength="100"
						required
					/>
				</div>
			</div>
			<div class="field">
				<label class="label" for="new-email">Adresse email</label><input
					id="new-email"
					class="input"
					type="email"
					bind:value={email}
					autocomplete="email"
					maxlength="254"
					required
				/>
			</div>
			<div class="field"><RoleSelector bind:selected={roles} disabled={busy} /></div>
			<fieldset class="field">
				<legend class="label">Promotions <span class="muted">· facultatif</span></legend>
				{#if promotionError}<p class="notification is-warning is-light">{promotionError}</p>{/if}
				{#if !eligible}<p class="help">
						L’affectation à une promotion nécessite le rôle Élève, Enseignant ou Khôlleur.
					</p>{:else}<div class="promotion-checks">
						{#each promotions as promotion (promotion.id)}<label class="checkbox"
								><input type="checkbox" value={promotion.id} bind:group={selected} /><PromotionTag
									{promotion}
								/></label
							>{/each}
						{#if promotions.length === 0 && !promotionError}<p class="muted text-small">
								Aucune promotion active disponible.
							</p>{/if}
					</div>{/if}
			</fieldset>
			<div class="dialog-actions">
				<button class="button is-light" type="button" onclick={onclose} disabled={busy}
					>Annuler</button
				><button class="button is-primary" class:is-loading={busy} disabled={busy} type="submit"
					><Icon name="plus" />Créer le compte</button
				>
			</div>
		</form>
	{/if}
</Modal>
