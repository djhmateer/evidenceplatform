export const SHARE_URL_PARAM = 'share';


export const getShareTokenFromHref = () => {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(SHARE_URL_PARAM);
}