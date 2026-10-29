<script lang="ts">
	import { formatDate, statusLabels } from '#lib/dashboard';
	import type { AccountActivity } from '#lib/types';
	import Icon from './Icon.svelte';
	let { activity, status }: { activity: AccountActivity; status: string } = $props();
</script>

<section class="workspace-panel account-activity">
	<p class="eyebrow">Activité et sécurité</p>
	<h2 class="title is-5"><Icon name="clock" />Les repères de votre compte</h2>
	<div class="activity-grid">
		<div>
			<span>Dernière connexion</span><strong>{formatDate(activity.last_login_at)}</strong>
		</div>
		<div>
			<span
				>Connexion{activity.login_count === 1 ? '' : 's'} réussie{activity.login_count === 1
					? ''
					: 's'}</span
			><strong>{activity.login_count}</strong>
		</div>
		<div><span>Compte créé le</span><strong>{formatDate(activity.created_at)}</strong></div>
		{#if 'updated_at' in activity}
			<div>
				<span>Dernière mise à jour</span><strong>{formatDate(activity.updated_at)}</strong>
			</div>
			<div>
				<span>Mot de passe modifié</span><strong>{formatDate(activity.password_changed_at)}</strong>
			</div>
			<div>
				<span>Email vérifié</span><strong
					>{activity.email_verified
						? formatDate(activity.email_verified_at)
						: 'Non vérifié'}</strong
				>
			</div>
		{/if}
	</div>
	<p class="help mt-4">
		{statusLabels[status]} · Dates à l’heure de Paris. La dernière connexion correspond à une authentification
		réussie.
	</p>
</section>
