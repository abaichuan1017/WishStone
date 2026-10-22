async (page) => {
  await page.goto("http://127.0.0.1:8080/brand/wishstone-icon.svg");
  for (const size of [1024, 512, 192, 32]) {
    await page.setViewportSize({width:size, height:size});
    await page.locator("svg").evaluate((svg, size) => {svg.setAttribute("width", size); svg.setAttribute("height", size);}, size);
    await page.locator("svg").screenshot({path:`app/static/brand/wishstone-icon-${size}.png`, omitBackground:true});
  }
  await page.setViewportSize({width:512,height:512});
  await page.locator("svg").evaluate(svg => {svg.setAttribute("width",512);svg.setAttribute("height",512)});
  await page.locator("svg").screenshot({path:"docs/assets/wishstone-icon.png",omitBackground:true});
  await page.goto("http://127.0.0.1:8080/brand/preview.html");
  await page.setViewportSize({width:1160,height:740});
  await page.screenshot({path:"docs/assets/icon-preview.png"});
  return {exported:6};
}
