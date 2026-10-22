async (page) => {
  const base = "http://127.0.0.1:8080";
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(base + "/");
  await page.getByRole("combobox", {name:"选择体验场馆"}).waitFor({state:"visible"});
  await page.waitForFunction(() => !document.getElementById("venueSelect").disabled);
  await page.evaluate(() => document.fonts.ready);
  const bottom = await page.locator(".journey").evaluate(el => Math.ceil(el.getBoundingClientRect().bottom + 22));
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  await page.screenshot({path:"docs/assets/kiosk-desktop.png", clip:{x:0,y:0,width,height:bottom}});
  await page.getByText("也可以写下心愿", {exact:false}).click();
  await page.getByRole("textbox", {name:"此刻，你有什么心愿？"}).fill("希望今年顺利毕业，也愿妈妈身体健康，家人平安。");
  await page.getByRole("button", {name:"安放心愿"}).click();
  await page.locator("#result").waitFor({state:"visible"});
  await page.getByRole("heading", {name:"璧·常安",exact:true}).first().waitFor();
  await page.locator("#result").evaluate(el => el.scrollIntoView({block:"center",behavior:"instant"}));
  const box = await page.locator("#result").boundingBox();
  await page.screenshot({path:"docs/assets/wish-result.png",clip:{x:box.x-24,y:Math.max(0,box.y-20),width:box.width+48,height:box.height+40}});
  const memoryPath = await page.getByRole("link", {name:"打开专属心愿页"}).getAttribute("href");
  await page.goto(base + memoryPath);
  await page.setViewportSize({width:390,height:1000});
  await page.locator("#memoryContent").waitFor({state:"visible"});
  await page.screenshot({path:"docs/assets/memory-mobile.png",fullPage:true});
  return {screenshots:3, demoInput:"文字心愿", physicalHardwareTested:false};
}
