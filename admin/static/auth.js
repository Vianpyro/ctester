// Connexion OIDC pour une page sans build : portage de
// frontend/src/lib/auth/oidc.ts, reduit a ce dont le tableau de bord a besoin.
// Les contraintes commentees la-bas valent ici aussi.

const TOKEN_KEY = "ctester-admin-token";
const REFRESH_KEY = "ctester-admin-refresh";
const EXPIRY_KEY = "ctester-admin-expiry";
const PKCE_KEY = "ctester-admin-pkce";

// Rauthy n'accepte un refresh token que dans la derniere minute du jeton d'acces,
// et s'en servir plus tot revoque toutes les sessions. 30 s reste dans la fenetre.
const REFRESH_MARGIN = 30;

let jeton = null;
let reglages = null;
let decouverte = null;
let enCours = null;        // un seul refresh a la fois : la rotation les invaliderait

const secondes = () => Math.floor(Date.now() / 1000);

function lire(cle) {
  try {
    return localStorage.getItem(cle) || "";
  } catch {
    return "";
  }
}

function ecrire(cle, valeur) {
  try {
    if (valeur) localStorage.setItem(cle, valeur);
    else localStorage.removeItem(cle);
  } catch {
    /* navigation privee : la session vivra le temps de l'onglet */
  }
}

async function config() {
  if (!reglages) {
    const reponse = await fetch("/api/oidc");
    reglages = await reponse.json();
    if (!reglages.issuer || !reglages.client_id) {
      throw new Error("la connexion n'est pas configuree sur ce deploiement");
    }
  }
  return reglages;
}

async function discovery() {
  if (!decouverte) {
    const { issuer } = await config();
    const reponse = await fetch(issuer + "/.well-known/openid-configuration");
    decouverte = await reponse.json();
  }
  return decouverte;
}

const base64url = (octets) =>
  btoa(String.fromCharCode(...octets))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");

const aleatoire = () => base64url(crypto.getRandomValues(new Uint8Array(32)));

// crypto.subtle n'existe qu'en contexte securise : sans HTTPS, la connexion est
// impossible, pas seulement degradee.
async function defiPour(verifieur) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifieur));
  return base64url(new Uint8Array(digest));
}

// L'URI enregistree cote Rauthy doit etre exactement celle-ci.
const redirection = () => location.origin + location.pathname;

function garder(octroi) {
  jeton = octroi.access_token || null;
  ecrire(TOKEN_KEY, jeton || "");
  ecrire(REFRESH_KEY, octroi.refresh_token || "");
  ecrire(EXPIRY_KEY, octroi.expires_in
    ? String(secondes() + Number(octroi.expires_in))
    : "");
}

export function oublier() {
  jeton = null;
  enCours = null;
  ecrire(TOKEN_KEY, "");
  ecrire(REFRESH_KEY, "");
  ecrire(EXPIRY_KEY, "");
}

function bientotExpire() {
  const fin = Number(lire(EXPIRY_KEY)) || 0;
  // Sans echeance connue on garde le jeton : un 401 declenchera le renouvellement,
  // alors qu'un renouvellement premature ferait revoquer la session.
  return fin > 0 && secondes() >= fin - REFRESH_MARGIN;
}

async function echanger(corps) {
  const doc = await discovery();
  const reponse = await fetch(doc.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(corps).toString(),
  });
  if (!reponse.ok) return null;
  try {
    return await reponse.json();
  } catch {
    return null;
  }
}

function rafraichirJeton() {
  if (enCours) return enCours;
  const porte = lire(REFRESH_KEY);
  if (!porte) return Promise.resolve(false);
  enCours = config()
    .then(({ client_id }) => echanger({
      grant_type: "refresh_token",
      refresh_token: porte,
      client_id,
    }))
    .then((octroi) => {
      enCours = null;
      if (!octroi || !octroi.access_token) {
        oublier();
        return false;
      }
      garder(octroi);
      return true;
    }, () => {
      enCours = null;
      return false;
    });
  return enCours;
}

/** Le jeton a envoyer, renouvele si besoin ; null quand il faut se reconnecter. */
export async function jetonValide() {
  // Relu du stockage apres un rechargement : sans ca on renouvellerait a chaque
  // ouverture de page, bien avant la fenetre que Rauthy autorise.
  if (!jeton) jeton = lire(TOKEN_KEY) || null;
  if (jeton && !bientotExpire()) return jeton;
  return (await rafraichirJeton()) ? jeton : null;
}

export async function connecter() {
  const doc = await discovery();
  const { client_id } = await config();
  const verifieur = aleatoire();
  const etat = aleatoire();
  try {
    sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifieur, etat }));
  } catch {
    throw new Error("le stockage de session est indisponible");
  }
  const params = new URLSearchParams({
    response_type: "code",
    client_id,
    redirect_uri: redirection(),
    scope: "openid profile offline_access",
    state: etat,
    code_challenge: await defiPour(verifieur),
    code_challenge_method: "S256",
  });
  location.assign(doc.authorization_endpoint + "?" + params.toString());
}

async function terminer(code, etat) {
  let garde = null;
  try {
    garde = JSON.parse(sessionStorage.getItem(PKCE_KEY) || "null");
    sessionStorage.removeItem(PKCE_KEY);
  } catch {
    garde = null;
  }
  // Sans cette verification, un lien portant le code de quelqu'un d'autre
  // connecterait a sa place.
  if (!garde || !garde.etat || garde.etat !== etat) return false;
  const { client_id } = await config();
  const octroi = await echanger({
    grant_type: "authorization_code",
    code,
    client_id,
    redirect_uri: redirection(),
    code_verifier: garde.verifieur || "",
  });
  if (!octroi || !octroi.access_token) return false;
  garder(octroi);
  return true;
}

/**
 * Retour de Rauthy s'il y a lieu, puis un jeton utilisable ou null.
 * Le code est retire de l'URL : un rechargement ne doit pas le rejouer.
 */
export async function demarrer() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code");
  const etat = params.get("state");
  if (code && etat) {
    const ouvert = await terminer(code, etat);
    history.replaceState(null, "", location.pathname);
    if (ouvert) return jeton;
  }
  return jetonValide();
}
