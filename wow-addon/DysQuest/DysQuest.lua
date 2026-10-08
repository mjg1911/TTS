local ADDON_NAME = ...

local function cleanText(text)
    if not text or text == "" then
        return nil
    end

    text = text:gsub("|c%x%x%x%x%x%x%x%x", "")
    text = text:gsub("|r", "")
    text = text:gsub("|H.-|h(.-)|h", "%1")
    text = text:gsub("|T.-|t", "")
    text = text:gsub("|A.-|a", "")
    text = text:gsub("\r", "")
    text = text:gsub("\n%s*\n+", "\n")
    return strtrim(text)
end

local function addText(parts, text)
    text = cleanText(text)
    if text and text ~= "" then
        for _, existing in ipairs(parts) do
            if existing == text then
                return
            end
        end
        table.insert(parts, text)
    end
end

local function readQuestText()
    local parts = {}

    addText(parts, QuestInfoTitleHeader and QuestInfoTitleHeader:GetText())
    addText(parts, QuestInfoDescriptionText and QuestInfoDescriptionText:GetText())
    addText(parts, QuestInfoObjectivesText and QuestInfoObjectivesText:GetText())

    if #parts == 0 then
        if QuestInfoFrame and QuestInfoFrame.questLog and GetQuestLogQuestText then
            addText(parts, GetQuestLogQuestText())
        elseif GetQuestText then
            addText(parts, GetTitleText and GetTitleText())
            addText(parts, GetQuestText())
            addText(parts, GetObjectiveText and GetObjectiveText())
        end
    end

    return table.concat(parts, "\n\n")
end

local popup = CreateFrame("Frame", "DysQuestPopup", UIParent, "BackdropTemplate")
popup:SetSize(600, 390)
popup:SetPoint("CENTER")
popup:SetFrameStrata("DIALOG")
popup:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true,
    tileSize = 32,
    edgeSize = 32,
    insets = { left = 8, right = 8, top = 8, bottom = 8 },
})
popup:Hide()

BINDING_HEADER_DYSQUEST = "DysQuest"
BINDING_NAME_DYSQUEST_CLOSE_WINDOW = "Close text window"

function DysQuest_CloseWindow()
    popup:Hide()
end

local title = popup:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
title:SetPoint("TOP", popup, "TOP", 0, -20)
title:SetText("Selected quest text")

local titleAccent = popup:CreateTexture(nil, "ARTWORK")
titleAccent:SetColorTexture(0.78, 0.61, 0.20, 0.9)
titleAccent:SetPoint("TOPLEFT", popup, "TOPLEFT", 30, -48)
titleAccent:SetPoint("TOPRIGHT", popup, "TOPRIGHT", -30, -48)
titleAccent:SetHeight(1)

local textPanel = CreateFrame("Frame", "DysQuestTextPanel", popup, "BackdropTemplate")
textPanel:SetPoint("TOPLEFT", popup, "TOPLEFT", 26, -60)
textPanel:SetPoint("BOTTOMRIGHT", popup, "BOTTOMRIGHT", -34, 46)
textPanel:SetBackdrop({
    bgFile = "Interface\\Buttons\\WHITE8X8",
    edgeFile = "Interface\\Buttons\\WHITE8X8",
    edgeSize = 1,
    insets = { left = 1, right = 1, top = 1, bottom = 1 },
})
textPanel:SetBackdropColor(0.025, 0.03, 0.045, 0.82)
textPanel:SetBackdropBorderColor(0.38, 0.34, 0.23, 0.72)

local hint = popup:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
hint:SetPoint("BOTTOM", popup, "BOTTOM", 0, 18)
hint:SetText("Press Escape to close.")

local scroll = CreateFrame("ScrollFrame", "DysQuestScroll", popup, "UIPanelScrollFrameTemplate")
scroll:SetPoint("TOPLEFT", textPanel, "TOPLEFT", 10, -10)
scroll:SetPoint("BOTTOMRIGHT", textPanel, "BOTTOMRIGHT", -30, 10)

local editBox = CreateFrame("EditBox", "DysQuestEditBox", scroll)
editBox:SetMultiLine(true)
editBox:SetAutoFocus(false)
editBox:SetPropagateKeyboardInput(true)
editBox:SetFontObject(GameFontHighlight)
editBox:SetWidth(480)
editBox:SetHeight(280)
editBox:SetScript("OnEscapePressed", DysQuest_CloseWindow)
scroll:SetScrollChild(editBox)

local closeButton = CreateFrame("Button", nil, popup, "UIPanelCloseButton")
closeButton:SetPoint("TOPRIGHT", popup, "TOPRIGHT", -5, -5)

local function selectQuestText()
    local text = readQuestText()
    if text == "" then
        text = "No quest text found. Open a quest detail window and try again."
    end

    editBox:SetText(text)
    editBox:SetCursorPosition(0)
    popup:Show()
    editBox:SetFocus()
    editBox:HighlightText()
end

local button = CreateFrame("Button", "DysQuestButton", UIParent, "UIPanelButtonTemplate")
button:SetSize(142, 24)
button:SetText("Select quest text")
button:SetScript("OnClick", selectQuestText)
button:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Select the open quest's title, description, and objectives.")
    GameTooltip:Show()
end)
button:SetScript("OnLeave", function()
    GameTooltip:Hide()
end)
button:Hide()

local hookedQuestFrame
local hookedMapDetails
local questDetailsOpen = false
local mapFunctionsHooked = false

local hookMapDetails

local function updateButton()
    hookMapDetails()

    local mapDetails = QuestMapFrame and QuestMapFrame.DetailsFrame
    if mapDetails and mapDetails.questID and mapDetails:IsVisible() then
        if button:GetParent() ~= mapDetails then
            button:SetParent(mapDetails)
        end
        button:ClearAllPoints()
        button:SetSize(96, 22)
        button:SetText("Select text")

        local backButton = mapDetails.BackFrame and mapDetails.BackFrame.BackButton
        if backButton then
            button:SetPoint("LEFT", backButton, "RIGHT", 6, 0)
        else
            button:SetPoint("TOPLEFT", mapDetails, "TOPLEFT", 108, -16)
        end

        button:Show()
        return
    end

    local questFrame = QuestFrame
    if not questFrame then
        button:Hide()
        return
    end

    if button:GetParent() ~= questFrame then
        button:SetParent(questFrame)
    end
    button:ClearAllPoints()
    button:SetSize(142, 24)
    button:SetText("Select quest text")
    local actionButton = QuestInfoFrame and QuestInfoFrame.acceptButton
    if not actionButton or not actionButton:IsShown() then
        actionButton = QuestFrameAcceptButton
    end

    if actionButton and actionButton:IsShown() then
        button:SetPoint("LEFT", actionButton, "RIGHT", 12, 0)
    else
        button:SetPoint("BOTTOMLEFT", questFrame, "BOTTOMLEFT", 170, 15)
    end

    button:SetShown(questDetailsOpen and questFrame:IsShown())

    if hookedQuestFrame ~= questFrame then
        questFrame:HookScript("OnShow", updateButton)
        questFrame:HookScript("OnHide", function()
            questDetailsOpen = false
            updateButton()
        end)
        hookedQuestFrame = questFrame
    end
end

hookMapDetails = function()
    local detailsFrame = QuestMapFrame and QuestMapFrame.DetailsFrame
    if detailsFrame and hookedMapDetails ~= detailsFrame then
        detailsFrame:HookScript("OnShow", updateButton)
        detailsFrame:HookScript("OnHide", updateButton)
        hookedMapDetails = detailsFrame
    end

    if not mapFunctionsHooked
        and type(QuestMapFrame_ShowQuestDetails) == "function"
        and type(QuestMapFrame_CloseQuestDetails) == "function"
    then
        hooksecurefunc("QuestMapFrame_ShowQuestDetails", updateButton)
        hooksecurefunc("QuestMapFrame_CloseQuestDetails", updateButton)
        mapFunctionsHooked = true
    end
end

local events = CreateFrame("Frame")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("QUEST_LOG_UPDATE")
events:RegisterEvent("QUEST_DETAIL")
events:RegisterEvent("QUEST_PROGRESS")
events:RegisterEvent("QUEST_COMPLETE")
events:RegisterEvent("QUEST_FINISHED")
events:RegisterEvent("GOSSIP_SHOW")
events:RegisterEvent("GOSSIP_CLOSED")
events:SetScript("OnEvent", function(_, event, loadedAddon)
    if event == "ADDON_LOADED"
        and loadedAddon ~= "Blizzard_UIPanels_Game"
        and loadedAddon ~= ADDON_NAME
    then
        return
    end

    if event == "QUEST_DETAIL" or event == "QUEST_PROGRESS" or event == "QUEST_COMPLETE" then
        questDetailsOpen = true
    elseif event == "QUEST_FINISHED" or event == "GOSSIP_SHOW" then
        questDetailsOpen = false
    end

    updateButton()
    if C_Timer and C_Timer.After then
        C_Timer.After(0, updateButton)
    end
end)

SLASH_DYSQUEST1 = "/dysquest"
SlashCmdList.DYSQUEST = selectQuestText
