export async function setItemAsync(k, v) { localStorage.setItem('ss_' + k, v); }
export async function getItemAsync(k) { return localStorage.getItem('ss_' + k); }
export async function deleteItemAsync(k) { localStorage.removeItem('ss_' + k); }
export const isAvailableAsync = async () => true;
