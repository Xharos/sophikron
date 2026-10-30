<script lang="ts">
	import { command, read } from '#lib/dashboard';
	import type { AccessInvitation } from '#lib/types';
	import type { CourseImpact } from '#lib/site';
	import Icon from '../Icon.svelte';
	import InvitationResult from '../InvitationResult.svelte';
	let {
		userId,
		status,
		currentUserId,
		onchanged
	}: {
		userId: number;
		status: string;
		currentUserId: number;
		onchanged: () => void | Promise<void>;
	} = $props();
	const account = $derived({ status });
	let busy = $state(false);
	let message = $state('');
	let invitation = $state<AccessInvitation | null>(null);
	let confirmation = $state<'archive' | 'invite' | null>(null);
	let impacts = $state<CourseImpact[]>([]);
	async function prepareArchive(): Promise<void> {
		busy = true;
		message = '';
		try {
			impacts = await read<CourseImpact[]>('courseImpact', { id: userId });
			confirmation = 'archive';
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
	async function perform(): Promise<void> {
		if (!account || !confirmation) return;
		busy = true;
		message = '';
		try {
			if (confirmation === 'archive') {
				await command('archiveAccount', {
					id: userId,
					data: { archived: account.status !== 'disabled', acknowledge_course_impact: true }
				});
				invitation = null;
			} else invitation = await command<AccessInvitation>('invitation', { id: userId });
			confirmation = null;
			await onchanged();
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			busy = false;
		}
	}
</script>

<section class="workspace-panel mt-5" aria-label="Accès au compte">
	<h2 class="title is-5">Accès au compte</h2>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	<div class="profile-buttons">
		<button
			class="button is-light"
			disabled={busy || account.status === 'disabled'}
			onclick={() => (confirmation = 'invite')}
			><Icon name="email" />{account.status === 'pending_activation'
				? 'Nouvelle invitation'
				: 'Réinitialiser le mot de passe'}</button
		>
		<button
			class="button"
			class:is-danger={account.status !== 'disabled'}
			class:is-light={account.status !== 'disabled'}
			disabled={busy || currentUserId === userId}
			onclick={prepareArchive}
			><Icon name={account.status === 'disabled' ? 'restore' : 'archive'} />{account.status ===
			'disabled'
				? 'Réactiver le compte'
				: 'Archiver le compte'}</button
		>
	</div>
	{#if currentUserId === userId}<p class="help mt-2">
			Votre propre compte ne peut pas être archivé.
		</p>{/if}
	{#if confirmation}<div
			class="confirmation-panel mt-4"
			role="group"
			aria-label="Confirmation de l’action"
		>
			<p>
				{confirmation === 'invite'
					? 'Une nouvelle invitation sera envoyée par email si configuré, sinon un lien sera affiché. Les anciens liens ne fonctionneront plus.'
					: account.status === 'disabled'
						? 'Ce compte pourra à nouveau être utilisé. Les anciens liens et sessions resteront invalides.'
						: 'Ce compte ne pourra plus se connecter et ses sessions seront fermées. Ses informations seront conservées.'}
			</p>
			<div class="buttons mt-3">
				{#if confirmation === 'archive' && account.status !== 'disabled' && impacts.length}<div
						class="notification is-warning is-light"
						role="alert"
					>
						<p>
							<strong>Ce compte est associé à {impacts.length} cours.</strong> L’archivage supprimera
							ses matières affectées et ses collaborations, et révoquera tous ses accès.
						</p>
						<ul>
							{#each impacts as course (course.id)}<li>{course.title}</li>{/each}
						</ul>
						<p>
							Réaffectez si nécessaire le responsable depuis les pages de cours. La réactivation ne
							rétablira pas automatiquement ces affectations.
						</p>
					</div>{/if}
				<button class="button is-primary" class:is-loading={busy} disabled={busy} onclick={perform}
					>Confirmer</button
				><button class="button is-light" disabled={busy} onclick={() => (confirmation = null)}
					>Annuler</button
				>
			</div>
		</div>{/if}
	{#if invitation}<InvitationResult {invitation} />{/if}
</section>
